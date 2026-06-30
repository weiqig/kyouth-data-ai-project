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
    field_definition_id: int | None = None
    template_key: str | None = None
    standard_field_key: str | None = None
    data_type: str | None = None
    required: bool = False
    validation_status: str | None = None
    validation_message: str | None = None
    validation_rule: str | None = None
    field_name: str
    extracted_value: str
    display_value: str
    confidence_score: float
    review_confidence_score: float
    review_status: str
    source_snippet: str
    source_line_number: int | None = None
    source_start_char: int | None = None
    source_end_char: int | None = None
    source_json_path: str | None = None
    source_row_index: int | None = None
    source_column_name: str | None = None
    ai_reasoning: str
    needs_review: bool
    accepted: bool
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    corrections: list[CorrectionOut] = []


class DocumentAIReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    model: str
    summary: str
    overall_confidence: float
    document_quality: str
    review_recommendation: str
    issues_json: str
    consistency_checks_json: str
    created_at: datetime


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
    document_type_key: str | None = None
    document_type_label: str | None = None
    extraction_mode: str = "auto_detect"
    original_file_size: int | None = None
    original_preview_text: str
    parser_type: str
    raw_text: str
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    extractions: list[ExtractionOut] = []
    jobs: list[ProcessingJobOut] = []
    ai_reviews: list[DocumentAIReviewOut] = []


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


class RejectDocumentIn(BaseModel):
    rejected_by: str = "demo_user"
    reason_code: str | None = None
    reason: str | None = None


class RejectionReasonOut(BaseModel):
    code: str
    label: str
    description: str


class TemplateFieldOut(BaseModel):
    key: str
    label: str
    data_type: str
    required: bool
    aliases: list[str] = []
    validation: dict = {}


class DocumentTemplateOut(BaseModel):
    key: str
    name: str
    industry: str
    description: str
    fields: list[TemplateFieldOut]
