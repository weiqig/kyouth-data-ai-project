from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..ai.controls import utcnow
from ..models import AuditLog, Document, DocumentStatus, Extraction
from ..review_policy import confidence_review_threshold, requires_confidence_review


def mark_extraction_accepted(extraction: Extraction, actor: str) -> None:
    """Mark an extraction as accepted using a Python datetime."""
    extraction.accepted = True
    extraction.needs_review = False
    extraction.accepted_by = actor
    extraction.accepted_at = utcnow()


def auto_accept_exact_display_matches(
    db: Session, document_id: int, actor: str = "system"
) -> int:
    """Auto-accept fields whose display value exactly matches extraction value.

    Low-confidence fields still require review regardless of exact matching.
    """
    candidates = db.scalars(
        select(Extraction)
        .where(Extraction.document_id == document_id, Extraction.accepted.is_(False))
        .options(selectinload(Extraction.corrections))
    ).all()

    accepted_count = 0
    accepted_names: list[str] = []
    threshold = confidence_review_threshold()
    for extraction in candidates:
        if requires_confidence_review(extraction.confidence_score):
            extraction.needs_review = True
            continue
        if extraction.validation_status in {"invalid", "missing_required"}:
            extraction.needs_review = True
            continue

        if extraction.extracted_value == extraction.display_value:
            mark_extraction_accepted(extraction, actor)
            accepted_count += 1
            accepted_names.append(extraction.field_name)

    if accepted_count:
        preview = ", ".join(accepted_names[:8])
        suffix = "" if accepted_count <= 8 else f", and {accepted_count - 8} more"
        db.add(
            AuditLog(
                document_id=document_id,
                action="fields_auto_accepted_exact_match",
                actor=actor,
                details=(
                    f"Auto-accepted {accepted_count} field(s) because the original extracted value "
                    f"exactly matched the current review/display value and met the {round(threshold * 100)}% confidence threshold: {preview}{suffix}."
                ),
            )
        )

    return accepted_count


def refresh_document_review_status(
    db: Session, document_id: int, actor: str = "system"
) -> str:
    """Approve only when every extraction is accepted and none need review."""
    document = db.get(Document, document_id)
    if not document:
        return "missing"

    if document.status in {
        DocumentStatus.ERROR.value,
        DocumentStatus.PENDING.value,
        DocumentStatus.REJECTED.value,
    }:
        return document.status

    auto_accept_exact_display_matches(db, document_id, actor=actor)

    total_fields = (
        db.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.document_id == document_id)
        )
        or 0
    )
    blocking_fields = (
        db.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(
                Extraction.document_id == document_id,
                or_(Extraction.needs_review.is_(True), Extraction.accepted.is_(False)),
            )
        )
        or 0
    )

    old_status = document.status
    document.status = (
        DocumentStatus.APPROVED.value
        if total_fields > 0 and blocking_fields == 0
        else DocumentStatus.NEEDS_REVIEW.value
    )

    if old_status != document.status:
        transition_details = (
            f"Document status changed from {old_status} to {document.status}. "
            f"Approval requires all {total_fields} fields accepted and zero fields needing review; "
            f"{blocking_fields} blocking field(s) remain."
        )
        db.add(
            AuditLog(
                document_id=document_id,
                action="document_state_changed",
                actor=actor,
                details=transition_details,
            )
        )
        if document.status == DocumentStatus.APPROVED.value:
            db.add(
                AuditLog(
                    document_id=document_id,
                    action="document_approved",
                    actor=actor,
                    details=(
                        f"Document approved by {actor}. "
                        f"All {total_fields} extracted field(s) are accepted and zero fields require review."
                    ),
                )
            )

    return document.status
