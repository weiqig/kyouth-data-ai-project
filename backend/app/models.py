from __future__ import annotations

from enum import Enum
from difflib import SequenceMatcher
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class DocumentStatus(str, Enum):
    PENDING = "pending"
    # User-facing document workflow states.
    # Technical processing lifecycle is tracked in processing_jobs and audit_logs.
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    ERROR = "error"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parser_type: Mapped[str] = mapped_column(String(80), default="raw_text")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=DocumentStatus.PENDING.value, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    extractions: Mapped[list["Extraction"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ProcessingJob(Base):
    """Durable job record. Redis/Celery carries only this id; PostgreSQL owns job state."""

    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(50), default=JobStatus.QUEUED.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="jobs")


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    extracted_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    source_snippet: Mapped[str] = mapped_column(Text, nullable=False)
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
        """Confidence for the currently displayed/reviewed value.

        The original AI confidence is intentionally preserved in confidence_score.
        Before a human review/correction exists, the display confidence remains
        the AI confidence so low-confidence fields are not accidentally upgraded.
        After review, similarity between original AI value and display value is
        used as a separate confidence signal:
        - exact same value: 100%
        - same after whitespace/case normalization: 98%
        - otherwise: textual similarity ratio
        """
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
