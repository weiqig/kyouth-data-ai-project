from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    old_value: str
    corrected_value: str
    corrected_by: str
    corrected_at: datetime


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    field_name: str
    extracted_value: str
    display_value: str
    confidence_score: float
    review_confidence_score: float
    review_status: str
    source_snippet: str
    ai_reasoning: str
    needs_review: bool
    accepted: bool
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    corrections: list[CorrectionOut] = []


class ProcessingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    attempts: int
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str | None = None
    content_type: str | None = None
    parser_type: str
    raw_text: str
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    extractions: list[ExtractionOut] = []
    jobs: list[ProcessingJobOut] = []


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    document_id: int | None = None
    action: str
    actor: str
    details: str
    created_at: datetime


class CapabilityOut(BaseModel):
    supported_extensions: list[str]
    supported_content_types: list[str]
    intentionally_deferred: list[str]


class CorrectionIn(BaseModel):
    corrected_value: str | None = None
    field_name: str | None = None
    corrected_by: str = "demo_user"


class AcceptExtractionIn(BaseModel):
    accepted_by: str = "demo_user"


class AddExtractionIn(BaseModel):
    field_name: str
    value: str
    source_snippet: str | None = None
    added_by: str = "demo_user"
