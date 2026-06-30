from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import AuditLog, Correction, Document, DocumentStatus, Extraction

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics")
def dashboard_metrics(db: Session = Depends(get_db)):
    """Operational dashboard metrics sourced from PostgreSQL."""
    status_rows = db.execute(
        select(Document.status, func.count(Document.id)).group_by(Document.status)
    ).all()
    status_counts = {status: count for status, count in status_rows}
    for status in ["pending", "needs_review", "approved", "rejected", "error"]:
        status_counts.setdefault(status, 0)

    parser_rows = db.execute(
        select(Document.parser_type, func.count(Document.id))
        .group_by(Document.parser_type)
        .order_by(func.count(Document.id).desc())
    ).all()

    total_extractions = db.scalar(select(func.count()).select_from(Extraction)) or 0
    accepted_extractions = (
        db.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.accepted.is_(True))
        )
        or 0
    )
    needs_review_fields = (
        db.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.needs_review.is_(True))
        )
        or 0
    )
    corrections_count = db.scalar(select(func.count()).select_from(Correction)) or 0
    manually_added_fields = (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "field_manually_added")
        )
        or 0
    )

    extraction_rows = db.scalars(
        select(Extraction).options(selectinload(Extraction.corrections))
    ).all()
    avg_ai_confidence = (
        round(
            sum(x.confidence_score for x in extraction_rows) / len(extraction_rows), 4
        )
        if extraction_rows
        else 0
    )
    avg_review_confidence = (
        round(
            sum(x.review_confidence_score for x in extraction_rows)
            / len(extraction_rows),
            4,
        )
        if extraction_rows
        else 0
    )

    review_queue = db.scalars(
        select(Document)
        .where(Document.status == DocumentStatus.NEEDS_REVIEW.value)
        .options(selectinload(Document.extractions))
        .order_by(Document.updated_at.desc())
        .limit(5)
    ).all()

    recent_rows = db.execute(
        select(AuditLog, Document.filename, Document.parser_type, Document.status)
        .outerjoin(Document, AuditLog.document_id == Document.id)
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    ).all()

    return {
        "status_counts": status_counts,
        "parser_counts": [
            {"parser_type": parser or "unknown", "count": count}
            for parser, count in parser_rows
        ],
        "extraction_metrics": {
            "total_fields": total_extractions,
            "accepted_fields": accepted_extractions,
            "needs_review_fields": needs_review_fields,
            "corrections": corrections_count,
            "manually_added_fields": manually_added_fields,
            "avg_ai_confidence": avg_ai_confidence,
            "avg_review_confidence": avg_review_confidence,
        },
        "review_queue": [
            {
                "id": doc.id,
                "filename": doc.filename or f"Raw text document #{doc.id}",
                "status": doc.status,
                "needs_review_fields": sum(
                    1 for x in doc.extractions if x.needs_review or not x.accepted
                ),
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            }
            for doc in review_queue
        ],
        "recent_activity": [
            {
                "id": log.id,
                "document_id": log.document_id,
                "filename": filename
                or (f"Document #{log.document_id}" if log.document_id else "System"),
                "parser_type": parser_type,
                "document_status": status,
                "action": log.action,
                "actor": log.actor,
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log, filename, parser_type, status in recent_rows
        ],
    }
