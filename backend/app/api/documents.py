from __future__ import annotations

import hashlib
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, Document, DocumentStatus, ProcessingJob
from ..parsers import UnsupportedDocumentType, parse_raw_text, parse_upload
from ..schemas import AuditLogOut, DocumentOut, RejectDocumentIn, RejectionReasonOut
from ..services.document_service import LOAD_OPTIONS, sort_document_extractions
from ..services.review_service import refresh_document_review_status
from ..services.template_service import infer_template_key, get_template_definition
from ..tasks import process_document_job

router = APIRouter(prefix="/documents", tags=["documents"])

REJECTION_REASONS = [
    {
        "code": "incomplete_document",
        "label": "Incomplete document",
        "description": "Required information is missing from the uploaded document.",
    },
    {
        "code": "wrong_document_type",
        "label": "Wrong document type",
        "description": "The uploaded file is not the expected type of business document.",
    },
    {
        "code": "invalid_template",
        "label": "Invalid template",
        "description": "The selected or detected template does not match the document.",
    },
    {
        "code": "unsupported_format",
        "label": "Unsupported or unreadable content",
        "description": "The file content cannot be reliably processed within the current MVP scope.",
    },
    {
        "code": "duplicate_document",
        "label": "Duplicate document",
        "description": "The document appears to duplicate a record that already exists.",
    },
    {
        "code": "poor_data_quality",
        "label": "Poor data quality",
        "description": "The document is too incomplete, inconsistent, or unclear to review confidently.",
    },
    {
        "code": "other",
        "label": "Other",
        "description": "A custom rejection reason is provided by the reviewer.",
    },
]


def rejection_reason_label(code: str | None) -> str:
    for reason in REJECTION_REASONS:
        if reason["code"] == code:
            return reason["label"]
    return "Other"


@router.get("/rejection-reasons", response_model=list[RejectionReasonOut])
def list_rejection_reasons():
    return REJECTION_REASONS


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile | None = File(default=None),
    raw_text: str | None = Form(default=None),
    document_type_key: str | None = Form(default="auto"),
    db: Session = Depends(get_db),
):
    filename = None
    content_type = None
    try:
        original_bytes: bytes | None = None
        if file:
            filename = file.filename
            content_type = file.content_type
            original_bytes = await file.read()
            parsed = parse_upload(filename, content_type, original_bytes)
        elif raw_text and raw_text.strip():
            original_bytes = raw_text.encode("utf-8")
            filename = "raw-text.txt"
            parsed = parse_raw_text(raw_text)
            content_type = "text/plain"
        else:
            raise HTTPException(
                status_code=400, detail="Upload a supported file or provide raw_text."
            )
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not parsed.raw_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No readable text could be extracted from this document.",
        )

    requested_mode = (document_type_key or "auto").strip()
    if requested_mode in {"discovery", "auto_discovery", "none"}:
        extraction_mode = "discovery"
        selected_template_key = None
    elif requested_mode in {"auto", "auto_detect"}:
        extraction_mode = "auto_detect"
        selected_template_key = infer_template_key(
            parsed.raw_text, parsed.parser_type, "auto"
        )
    else:
        extraction_mode = "template"
        selected_template_key = infer_template_key(
            parsed.raw_text, parsed.parser_type, requested_mode
        )

    selected_template = (
        get_template_definition(selected_template_key)
        if selected_template_key
        else None
    )

    doc = Document(
        filename=filename,
        content_type=content_type,
        document_type_key=selected_template.key if selected_template else None,
        document_type_label=selected_template.name if selected_template else None,
        extraction_mode=extraction_mode,
        parser_type=parsed.parser_type,
        raw_text=parsed.raw_text,
        original_file_data=original_bytes,
        original_file_size=len(original_bytes or b""),
        content_hash=hashlib.sha256(
            original_bytes or parsed.raw_text.encode("utf-8")
        ).hexdigest(),
        status=DocumentStatus.PENDING.value,
    )
    db.add(doc)
    db.flush()

    job = ProcessingJob(document_id=doc.id)
    db.add(job)
    db.add(
        AuditLog(
            document_id=doc.id,
            action="document_created",
            actor="api",
            details=(
                f"Raw input parsed via {parsed.parser_type}; document and durable processing job stored in PostgreSQL."
                + (
                    f" Mode: {extraction_mode}. Template selected: {selected_template.name}."
                    if selected_template
                    else f" Mode: {extraction_mode}. No template selected; free discovery extraction will be used."
                )
            ),
        )
    )
    db.add(
        AuditLog(
            document_id=doc.id,
            action="job_queued",
            actor="api",
            details="Celery received only the PostgreSQL processing_jobs.id.",
        )
    )
    db.commit()
    db.refresh(doc)
    db.refresh(job)

    process_document_job.delay(job.id)
    return sort_document_extractions(
        db.scalar(select(Document).where(Document.id == doc.id).options(*LOAD_OPTIONS))
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    status: str | None = Query(
        default=None,
        description="Filter by document review status: pending, needs_review, approved, rejected, or error.",
    ),
    q: str | None = Query(
        default=None,
        description="Search filename, content type, parser type, error message, or raw text.",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    include_rejected: bool = Query(
        default=False,
        description="Include rejected records. Main dashboard keeps these hidden; database records page can enable this.",
    ),
    db: Session = Depends(get_db),
):
    stmt = select(Document).options(*LOAD_OPTIONS)

    if status and status != "all":
        stmt = stmt.where(Document.status == status)
    elif not include_rejected:
        stmt = stmt.where(Document.status != DocumentStatus.REJECTED.value)

    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Document.filename.ilike(term),
                Document.content_type.ilike(term),
                Document.parser_type.ilike(term),
                Document.document_type_key.ilike(term),
                Document.document_type_label.ilike(term),
                Document.raw_text.ilike(term),
                Document.error_message.ilike(term),
            )
        )

    documents = db.scalars(stmt.order_by(Document.created_at.desc()).limit(limit)).all()
    changed = False
    for document in documents:
        if document.status in {
            DocumentStatus.NEEDS_REVIEW.value,
            DocumentStatus.APPROVED.value,
        }:
            before = document.status
            refresh_document_review_status(db, document.id, actor="system")
            changed = changed or document.status != before
    if changed:
        db.commit()
    for document in documents:
        sort_document_extractions(document)
    return documents


@router.patch("/{document_id}/reject", response_model=DocumentOut)
def reject_document(
    document_id: int, payload: RejectDocumentIn, db: Session = Depends(get_db)
):
    doc = db.scalar(
        select(Document).where(Document.id == document_id).options(*LOAD_OPTIONS)
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status not in {
        DocumentStatus.PENDING.value,
        DocumentStatus.NEEDS_REVIEW.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="Only pending or needs_review documents can be rejected.",
        )

    old_status = doc.status
    doc.status = DocumentStatus.REJECTED.value

    reason_code = payload.reason_code or "other"
    reason_label = rejection_reason_label(reason_code)
    custom_reason = (
        payload.reason.strip() if payload.reason and payload.reason.strip() else ""
    )
    stored_reason = (
        reason_label if not custom_reason else f"{reason_label}: {custom_reason}"
    )
    doc.error_message = stored_reason

    details = f"Document status changed from {old_status} to rejected by {payload.rejected_by}. Reason: {stored_reason} (code: {reason_code})."

    db.add(
        AuditLog(
            document_id=document_id,
            action="document_rejected",
            actor=payload.rejected_by,
            details=details,
        )
    )
    db.add(
        AuditLog(
            document_id=document_id,
            action="document_state_changed",
            actor=payload.rejected_by,
            details=details,
        )
    )
    db.commit()
    return sort_document_extractions(
        db.scalar(
            select(Document).where(Document.id == document_id).options(*LOAD_OPTIONS)
        )
    )


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.scalar(
        select(Document).where(Document.id == document_id).options(*LOAD_OPTIONS)
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status in {DocumentStatus.NEEDS_REVIEW.value, DocumentStatus.APPROVED.value}:
        refresh_document_review_status(db, document_id, actor="system")
        db.commit()
        doc = db.scalar(
            select(Document).where(Document.id == document_id).options(*LOAD_OPTIONS)
        )
    return sort_document_extractions(doc)


@router.get("/{document_id}/download")
def download_original_document(
    document_id: int,
    actor: str = Query(
        default="demo_user",
        description="Actor recorded in the audit trail for the download event.",
    ),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if not doc or doc.original_file_data is None:
        raise HTTPException(
            status_code=404, detail="Original file bytes not found for this document"
        )

    filename = doc.filename or f"document-{doc.id}.txt"
    safe_filename = quote(filename)

    db.add(
        AuditLog(
            document_id=doc.id,
            action="document_downloaded",
            actor=actor or "demo_user",
            details=f'Original uploaded file "{filename}" downloaded from PostgreSQL storage.',
        )
    )
    db.commit()

    return Response(
        content=doc.original_file_data,
        media_type=doc.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
            "X-Document-Id": str(doc.id),
        },
    )


@router.get("/{document_id}/audit-logs", response_model=list[AuditLogOut])
def document_audit_logs(document_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.document_id == document_id)
        .order_by(AuditLog.created_at.asc())
    ).all()
