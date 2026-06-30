from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import engine
from ..models import Document, DocumentStatus
from .review_service import refresh_document_review_status


def normalize_legacy_document_statuses() -> None:
    """Map older prototype technical statuses and enforce approval rules."""
    with Session(engine) as db:
        db.execute(update(Document).where(Document.status == "processed").values(status=DocumentStatus.NEEDS_REVIEW.value))
        db.execute(update(Document).where(Document.status == "processing").values(status=DocumentStatus.PENDING.value))
        for document_id in db.scalars(
            select(Document.id).where(Document.status.in_([DocumentStatus.APPROVED.value, DocumentStatus.NEEDS_REVIEW.value]))
        ):
            refresh_document_review_status(db, document_id, actor="system")
        db.commit()
