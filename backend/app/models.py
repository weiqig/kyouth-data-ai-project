from __future__ import annotations

from enum import Enum
from difflib import SequenceMatcher
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float, LargeBinary, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class DocumentStatus(str, Enum):
    PENDING = "pending"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentTemplate(Base):
    __tablename__ = "document_templates"
    __table_args__ = (UniqueConstraint("template_key", name="uq_document_templates_template_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    fields: Mapped[list["FieldDefinition"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class FieldDefinition(Base):
    __tablename__ = "field_definitions"
    __table_args__ = (UniqueConstraint("template_id", "field_key", name="uq_field_definitions_template_field_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("document_templates.id", ondelete="CASCADE"), index=True)
    field_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    display_label: Mapped[str] = mapped_column(String(180), nullable=False)
    data_type: Mapped[str] = mapped_column(String(80), default="string")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped[DocumentTemplate] = relationship(back_populates="fields")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    document_type_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    document_type_label: Mapped[str | None] = mapped_column(String(180), nullable=True)
    extraction_mode: Mapped[str] = mapped_column(String(50), default="auto_detect", index=True)
    original_file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    original_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_type: Mapped[str] = mapped_column(String(80), default="raw_text")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default=DocumentStatus.PENDING.value, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deferred_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def original_preview_text(self) -> str:
        """Return a review-friendly preview while preserving immutable file bytes."""
        if self.original_file_data:
            content_type = (self.content_type or '').split(';')[0].lower()
            if self.parser_type in {'plain_text', 'raw_text', 'markdown', 'json', 'csv'} or content_type.startswith('text/') or content_type in {'application/json', 'text/csv', 'application/csv'}:
                return self.original_file_data.decode('utf-8-sig', errors='replace')
        return self.raw_text

    @property
    def latest_action_actor(self) -> str | None:
        if not self.audit_logs:
            return None
        return sorted(self.audit_logs, key=lambda item: (item.created_at or self.created_at, item.id or 0))[-1].actor

    @property
    def latest_action(self) -> str | None:
        if not self.audit_logs:
            return None
        return sorted(self.audit_logs, key=lambda item: (item.created_at or self.created_at, item.id or 0))[-1].action

    @property
    def latest_action_at(self):
        if not self.audit_logs:
            return None
        return sorted(self.audit_logs, key=lambda item: (item.created_at or self.created_at, item.id or 0))[-1].created_at

    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="document", order_by="AuditLog.created_at", passive_deletes=True
    )
    extractions: Mapped[list["Extraction"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    ai_reviews: Mapped[list["DocumentAIReview"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentAIReview.created_at"
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(50), default=JobStatus.QUEUED.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deferred_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="jobs")


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    field_definition_id: Mapped[int | None] = mapped_column(ForeignKey("field_definitions.id", ondelete="SET NULL"), nullable=True, index=True)
    template_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    standard_field_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    data_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    extracted_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    source_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    source_line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_json_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_column_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    ai_reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accepted_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="extractions")
    corrections: Mapped[list["Correction"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan", order_by="Correction.corrected_at"
    )

    @property
    def display_value(self) -> str:
        return self.corrections[-1].corrected_value if self.corrections else self.extracted_value

    @staticmethod
    def _normalized_for_review(value: str) -> str:
        return " ".join((value or "").strip().lower().split())

    @property
    def review_confidence_score(self) -> float:
        """Return confidence for the current reviewed value."""
        if not self.corrections:
            return round(float(self.confidence_score), 4)

        original = self.extracted_value or ""
        reviewed = self.display_value or ""
        if original == reviewed:
            return 1.0

        normalized_original = self._normalized_for_review(original)
        normalized_reviewed = self._normalized_for_review(reviewed)
        if normalized_original and normalized_original == normalized_reviewed:
            return 0.98

        if not normalized_original and not normalized_reviewed:
            return 1.0
        if not normalized_original or not normalized_reviewed:
            return 0.0

        return round(SequenceMatcher(None, normalized_original, normalized_reviewed).ratio(), 4)

    @property
    def review_status(self) -> str:
        if not self.accepted:
            return "awaiting_acceptance" if not self.needs_review else "needs_review"
        if not self.corrections:
            return "accepted_original"
        if self.review_confidence_score >= 0.98:
            return "accepted_same"
        if self.review_confidence_score >= 0.75:
            return "accepted_minor_change"
        return "accepted_modified"


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("extractions.id", ondelete="CASCADE"), index=True)
    old_value: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[str] = mapped_column(String(120), default="demo_user")
    corrected_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    extraction: Mapped[Extraction] = relationship(back_populates="corrections")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document | None] = relationship(back_populates="audit_logs")


class DocumentAIReview(Base):
    """Reviewer briefing generated by AI or deterministic fallback."""

    __tablename__ = "document_ai_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    document_quality: Mapped[str] = mapped_column(String(80), default="unknown")
    review_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    consistency_checks_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="ai_reviews")


class AIRequestCache(Base):
    """Cached AI extraction result keyed by content/provider/model."""

    __tablename__ = "ai_request_cache"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_ai_request_cache_cache_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parser_type: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    use_count: Mapped[int] = mapped_column(Integer, default=0)


class AIRateLimitWindow(Base):
    """Database-backed provider quota counter."""

    __tablename__ = "ai_rate_limit_windows"
    __table_args__ = (UniqueConstraint("provider", "model", "window_type", "window_start", name="uq_ai_rate_window"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    window_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    window_start = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    limit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
