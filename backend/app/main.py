from __future__ import annotations

import os
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select, update, text, func
from sqlalchemy.orm import Session, selectinload

from .db import Base, engine, get_db
from .models import AuditLog, Correction, Document, DocumentStatus, Extraction, ProcessingJob
from .parsers import SUPPORTED_CONTENT_TYPES, SUPPORTED_EXTENSIONS, UnsupportedDocumentType, parse_raw_text, parse_upload
from .schemas import AcceptExtractionIn, AddExtractionIn, AuditLogOut, CapabilityOut, CorrectionIn, DocumentOut
from .ai.service import AISettings
from .tasks import process_document_job
from .recovery import enqueue_recoverable_jobs

Base.metadata.create_all(bind=engine)


def ensure_review_acceptance_columns() -> None:
    """Lightweight dev migration for existing prototype databases.

    create_all() does not alter existing tables, so older local Docker volumes
    need these columns added without requiring a full migration framework yet.
    """
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS accepted BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS accepted_by VARCHAR(120)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP WITH TIME ZONE"))


def refresh_document_review_status(db: Session, document_id: int, actor: str = 'system') -> str:
    """Approve only when every extraction is accepted and none need review."""
    document = db.get(Document, document_id)
    if not document:
        return 'missing'

    if document.status in {DocumentStatus.ERROR.value, DocumentStatus.PENDING.value}:
        return document.status

    total_fields = db.scalar(select(func.count()).select_from(Extraction).where(Extraction.document_id == document_id)) or 0
    blocking_fields = db.scalar(
        select(func.count()).select_from(Extraction).where(
            Extraction.document_id == document_id,
            or_(Extraction.needs_review.is_(True), Extraction.accepted.is_(False)),
        )
    ) or 0

    old_status = document.status
    document.status = (
        DocumentStatus.APPROVED.value
        if total_fields > 0 and blocking_fields == 0
        else DocumentStatus.NEEDS_REVIEW.value
    )

    if old_status != document.status:
        transition_details = (
            f'Document status changed from {old_status} to {document.status}. '
            f'Approval requires all {total_fields} fields accepted and zero fields needing review; '
            f'{blocking_fields} blocking field(s) remain.'
        )
        db.add(AuditLog(
            document_id=document_id,
            action='document_state_changed',
            actor=actor,
            details=transition_details,
        ))
        if document.status == DocumentStatus.APPROVED.value:
            db.add(AuditLog(
                document_id=document_id,
                action='document_approved',
                actor=actor,
                details=(
                    f'Document approved by {actor}. '
                    f'All {total_fields} extracted field(s) are accepted and zero fields require review.'
                ),
            ))

    return document.status


ensure_review_acceptance_columns()

app = FastAPI(title='Audit-Ready AI Document Processing Pipeline')

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv('FRONTEND_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(',')],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)



DEBUG_TABLE_MODELS = {
    'documents': Document,
    'processing_jobs': ProcessingJob,
    'extractions': Extraction,
    'corrections': Correction,
    'audit_logs': AuditLog,
}


def serialize_debug_row(row):
    data = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if hasattr(value, 'isoformat'):
            value = value.isoformat()
        data[column.name] = value
    return data


def apply_debug_search(stmt, model, q: str | None):
    if not q or not q.strip():
        return stmt
    term = f"%{q.strip()}%"
    conditions = []
    for column in model.__table__.columns:
        if str(column.type).lower().startswith(('varchar', 'text')):
            conditions.append(column.ilike(term))
    if conditions:
        stmt = stmt.where(or_(*conditions))
    return stmt


LOAD_OPTIONS = (
    selectinload(Document.extractions).selectinload(Extraction.corrections),
    selectinload(Document.jobs),
)


def normalize_legacy_document_statuses() -> None:
    """Map older prototype technical statuses and enforce approval rules."""
    with Session(engine) as db:
        db.execute(update(Document).where(Document.status == "processed").values(status=DocumentStatus.NEEDS_REVIEW.value))
        db.execute(update(Document).where(Document.status == "processing").values(status=DocumentStatus.PENDING.value))
        for document_id in db.scalars(select(Document.id).where(Document.status.in_([DocumentStatus.APPROVED.value, DocumentStatus.NEEDS_REVIEW.value]))):
            refresh_document_review_status(db, document_id, actor='system')
        db.commit()


normalize_legacy_document_statuses()




@app.get('/debug/tables')
def debug_tables():
    """List available database tables for the developer debug UI.

    This endpoint is intentionally read-only. For a production deployment, protect
    it behind authentication or disable it with an environment flag.
    """
    return [
        {'name': name, 'columns': [column.name for column in model.__table__.columns]}
        for name, model in DEBUG_TABLE_MODELS.items()
    ]


@app.get('/debug/tables/{table_name}')
def debug_table_rows(
    table_name: str,
    q: str | None = Query(default=None, description='Optional text search across text/varchar columns.'),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Return rows for one table for the developer debug UI.

    The query is read-only and limited to known ORM models to avoid arbitrary SQL.
    """
    model = DEBUG_TABLE_MODELS.get(table_name)
    if not model:
        raise HTTPException(status_code=404, detail='Unknown debug table')

    stmt = select(model)
    stmt = apply_debug_search(stmt, model, q)
    stmt = stmt.order_by(model.id.desc()).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()
    return {
        'table': table_name,
        'columns': [column.name for column in model.__table__.columns],
        'limit': limit,
        'offset': offset,
        'rows': [serialize_debug_row(row) for row in rows],
    }


@app.get('/health')
def health():
    return {'ok': True, 'architecture': 'postgres-state-driven'}


@app.get('/capabilities', response_model=CapabilityOut)
def capabilities():
    return {
        'supported_extensions': sorted(SUPPORTED_EXTENSIONS),
        'supported_content_types': sorted(SUPPORTED_CONTENT_TYPES),
        'intentionally_deferred': [
            'scanned PDFs and image OCR',
            'Office files such as docx/xlsx/pptx',
            'email files and archives',
            'vector search and advanced auth',
        ],
    }


@app.post('/documents', response_model=DocumentOut)
async def upload_document(
    file: UploadFile | None = File(default=None),
    raw_text: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    filename = None
    content_type = None
    try:
        if file:
            filename = file.filename
            content_type = file.content_type
            parsed = parse_upload(filename, content_type, await file.read())
        elif raw_text and raw_text.strip():
            parsed = parse_raw_text(raw_text)
            content_type = 'text/plain'
        else:
            raise HTTPException(status_code=400, detail='Upload a supported file or provide raw_text.')
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not parsed.raw_text.strip():
        raise HTTPException(status_code=400, detail='No readable text could be extracted from this document.')

    doc = Document(
        filename=filename,
        content_type=content_type,
        parser_type=parsed.parser_type,
        raw_text=parsed.raw_text,
        status=DocumentStatus.PENDING.value,
    )
    db.add(doc)
    db.flush()

    job = ProcessingJob(document_id=doc.id)
    db.add(job)
    db.add(AuditLog(
        document_id=doc.id,
        action='document_created',
        actor='api',
        details=f'Raw input parsed via {parsed.parser_type}; document and durable processing job stored in PostgreSQL.',
    ))
    db.add(AuditLog(document_id=doc.id, action='job_queued', actor='api', details='Celery received only the PostgreSQL processing_jobs.id.'))
    db.commit()
    db.refresh(doc)
    db.refresh(job)

    process_document_job.delay(job.id)

    return db.scalar(select(Document).where(Document.id == doc.id).options(*LOAD_OPTIONS))


@app.post('/jobs/requeue-pending')
def requeue_pending_jobs(db: Session = Depends(get_db)):
    """Recreate Celery messages for durable jobs still pending in PostgreSQL.

    Useful after early prototype crashes, Redis resets, worker restarts, or deploys.
    The worker still receives only processing_jobs.id; all state remains in PostgreSQL.
    """
    return enqueue_recoverable_jobs(db)




@app.get('/ai/config')
def ai_config():
    """Return safe AI runtime configuration for debugging.

    Secrets such as API keys are intentionally not returned.
    """
    settings = AISettings.from_env()
    return {
        'enabled': settings.enabled,
        'provider': settings.provider,
        'apply_to_parser_types': sorted(settings.apply_to_parser_types),
        'fallback_to_deterministic': settings.fallback_to_deterministic,
    }


@app.get('/documents', response_model=list[DocumentOut])
def list_documents(
    status: str | None = Query(default=None, description="Filter by document review status: pending, needs_review, approved, or error."),
    q: str | None = Query(default=None, description="Search filename, content type, parser type, error message, or raw text."),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return current database records with optional PostgreSQL-backed filters.

    The records page uses this endpoint for asynchronous search/filter updates.
    Filtering happens in PostgreSQL, not only in browser memory.
    """
    stmt = select(Document).options(*LOAD_OPTIONS)

    if status and status != 'all':
        stmt = stmt.where(Document.status == status)

    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Document.filename.ilike(term),
                Document.content_type.ilike(term),
                Document.parser_type.ilike(term),
                Document.raw_text.ilike(term),
                Document.error_message.ilike(term),
            )
        )

    stmt = stmt.order_by(Document.created_at.desc()).limit(limit)
    return db.scalars(stmt).all()


@app.get('/documents/{document_id}', response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.scalar(select(Document).where(Document.id == document_id).options(*LOAD_OPTIONS))
    if not doc:
        raise HTTPException(status_code=404, detail='Document not found')
    return doc


@app.get('/documents/{document_id}/audit-logs', response_model=list[AuditLogOut])
def document_audit_logs(document_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(AuditLog).where(AuditLog.document_id == document_id).order_by(AuditLog.created_at.asc())
    ).all()


@app.post('/documents/{document_id}/extractions')
def add_missing_extraction(document_id: int, payload: AddExtractionIn, db: Session = Depends(get_db)):
    """Add a missing field during human review.

    This is intentionally treated as a user-created extraction row rather than
    AI output. It starts accepted because the reviewer supplied it, and the
    audit trail records that it was manually added.
    """
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail='Document not found')

    field_name = payload.field_name.strip()
    value = payload.value.strip()
    if not field_name:
        raise HTTPException(status_code=400, detail='field_name is required')
    if not value:
        raise HTTPException(status_code=400, detail='value is required')

    extraction = Extraction(
        document_id=document_id,
        field_name=field_name,
        extracted_value=value,
        confidence_score=1.0,
        source_snippet=(payload.source_snippet or 'Manually added by reviewer; not present as an AI-extracted field.')[:500],
        ai_reasoning='Manually added by reviewer because this field was absent from the extracted fields. Not generated by AI.',
        needs_review=False,
        accepted=True,
        accepted_by=payload.added_by,
        accepted_at=func.now(),
    )
    db.add(extraction)
    db.flush()

    refresh_document_review_status(db, document_id, actor=payload.added_by)
    db.add(AuditLog(
        document_id=document_id,
        action='field_manually_added',
        actor=payload.added_by,
        details=f'{field_name}: manually added with value "{value}" and accepted immediately.',
    ))
    db.commit()
    return {'ok': True, 'id': extraction.id, 'document_status': document.status}


@app.patch('/extractions/{extraction_id}/correct')
def correct_extraction(extraction_id: int, payload: CorrectionIn, db: Session = Depends(get_db)):
    extraction = db.scalar(select(Extraction).where(Extraction.id == extraction_id).options(selectinload(Extraction.corrections)))
    if not extraction:
        raise HTTPException(status_code=404, detail='Extraction not found')

    old_field_name = extraction.field_name
    old_display_value = extraction.display_value
    old_review_confidence = extraction.review_confidence_score
    old_review_status = extraction.review_status

    new_field_name = (payload.field_name or extraction.field_name).strip()
    new_display_value = payload.corrected_value if payload.corrected_value is not None else old_display_value

    if not new_field_name:
        raise HTTPException(status_code=400, detail='field_name cannot be empty')
    if new_display_value is None or not str(new_display_value).strip():
        raise HTTPException(status_code=400, detail='corrected_value cannot be empty')

    field_name_changed = new_field_name != old_field_name
    value_changed = new_display_value != old_display_value
    if not field_name_changed and not value_changed and extraction.accepted and not extraction.needs_review:
        return {
            'ok': True,
            'ai_confidence_score': extraction.confidence_score,
            'review_confidence_score': extraction.review_confidence_score,
            'review_status': extraction.review_status,
            'accepted': extraction.accepted,
            'needs_review': extraction.needs_review,
        }

    if field_name_changed:
        extraction.field_name = new_field_name
        db.add(AuditLog(
            document_id=extraction.document_id,
            action='field_name_changed',
            actor=payload.corrected_by,
            details=f'Extraction field name changed from "{old_field_name}" to "{new_field_name}".',
        ))

    if value_changed:
        correction = Correction(
            extraction_id=extraction_id,
            old_value=old_display_value,
            corrected_value=new_display_value,
            corrected_by=payload.corrected_by,
        )
        db.add(correction)
        db.flush()

    # Saving a field update also accepts this field. Approval is document-level
    # and only happens after every field is accepted and no fields need review.
    extraction.needs_review = False
    extraction.accepted = True
    extraction.accepted_by = payload.corrected_by
    extraction.accepted_at = func.now()
    db.flush()

    new_review_confidence = extraction.review_confidence_score
    new_review_status = extraction.review_status
    refresh_document_review_status(db, extraction.document_id, actor=payload.corrected_by)

    details = []
    if field_name_changed:
        details.append(f'field name changed from "{old_field_name}" to "{new_field_name}"')
    if value_changed:
        details.append(f'display value changed from "{old_display_value}" to "{new_display_value}"')
    if not details:
        details.append(f'field "{extraction.field_name}" accepted without changes')

    db.add(AuditLog(
        document_id=extraction.document_id,
        action='field_reviewed',
        actor=payload.corrected_by,
        details=(
            f'{extraction.field_name}: ' + '; '.join(details) + '. '
            f'AI confidence preserved at {round(extraction.confidence_score * 100)}%. '
            f'Review confidence changed from {round(old_review_confidence * 100)}% ({old_review_status}) '
            f'to {round(new_review_confidence * 100)}% ({new_review_status}).'
        ),
    ))
    db.commit()
    return {
        'ok': True,
        'ai_confidence_score': extraction.confidence_score,
        'review_confidence_score': extraction.review_confidence_score,
        'review_status': extraction.review_status,
        'accepted': extraction.accepted,
        'needs_review': extraction.needs_review,
    }


@app.patch('/extractions/{extraction_id}/accept')
def accept_extraction(extraction_id: int, payload: AcceptExtractionIn, db: Session = Depends(get_db)):
    extraction = db.scalar(select(Extraction).where(Extraction.id == extraction_id).options(selectinload(Extraction.corrections)))
    if not extraction:
        raise HTTPException(status_code=404, detail='Extraction not found')

    old_review_status = extraction.review_status
    old_review_confidence = extraction.review_confidence_score

    extraction.needs_review = False
    extraction.accepted = True
    extraction.accepted_by = payload.accepted_by
    extraction.accepted_at = func.now()
    db.flush()

    refresh_document_review_status(db, extraction.document_id, actor=payload.accepted_by)
    db.add(AuditLog(
        document_id=extraction.document_id,
        action='field_accepted',
        actor=payload.accepted_by,
        details=(
            f'{extraction.field_name}: accepted display value "{extraction.display_value}". '
            f'Review confidence remained {round(old_review_confidence * 100)}%; '
            f'review status changed from {old_review_status} to {extraction.review_status}.'
        ),
    ))
    db.commit()

    return {
        'ok': True,
        'accepted': extraction.accepted,
        'needs_review': extraction.needs_review,
        'review_confidence_score': extraction.review_confidence_score,
        'review_status': extraction.review_status,
    }
