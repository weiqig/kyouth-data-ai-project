"""Initial Phase 1 schema.

Revision ID: 0001_initial_phase1_schema
Revises:
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_phase1_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("template_key", name="uq_document_templates_template_key"),
    )
    op.create_index("ix_document_templates_id", "document_templates", ["id"])
    op.create_index("ix_document_templates_template_key", "document_templates", ["template_key"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("document_type_key", sa.String(length=120), nullable=True),
        sa.Column("document_type_label", sa.String(length=180), nullable=True),
        sa.Column("extraction_mode", sa.String(length=50), nullable=False, server_default="auto_detect"),
        sa.Column("original_file_data", sa.LargeBinary(), nullable=True),
        sa.Column("original_file_size", sa.Integer(), nullable=True),
        sa.Column("parser_type", sa.String(length=80), nullable=False, server_default="raw_text"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("deferred_reason", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_documents_id", "documents", ["id"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_document_type_key", "documents", ["document_type_key"])
    op.create_index("ix_documents_extraction_mode", "documents", ["extraction_mode"])

    op.create_table(
        "field_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("document_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_key", sa.String(length=120), nullable=False),
        sa.Column("display_label", sa.String(length=180), nullable=False),
        sa.Column("data_type", sa.String(length=80), nullable=False, server_default="string"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("aliases_json", sa.Text(), nullable=True),
        sa.Column("validation_json", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("template_id", "field_key", name="uq_field_definitions_template_field_key"),
    )
    op.create_index("ix_field_definitions_id", "field_definitions", ["id"])
    op.create_index("ix_field_definitions_template_id", "field_definitions", ["template_id"])
    op.create_index("ix_field_definitions_field_key", "field_definitions", ["field_key"])

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("deferred_reason", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_processing_jobs_id", "processing_jobs", ["id"])
    op.create_index("ix_processing_jobs_document_id", "processing_jobs", ["document_id"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index("ix_processing_jobs_next_retry_at", "processing_jobs", ["next_retry_at"])

    op.create_table(
        "extractions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_definition_id", sa.Integer(), sa.ForeignKey("field_definitions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_key", sa.String(length=120), nullable=True),
        sa.Column("standard_field_key", sa.String(length=120), nullable=True),
        sa.Column("data_type", sa.String(length=80), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("validation_status", sa.String(length=50), nullable=True),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("validation_rule", sa.Text(), nullable=True),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("source_snippet", sa.Text(), nullable=False),
        sa.Column("source_line_number", sa.Integer(), nullable=True),
        sa.Column("source_start_char", sa.Integer(), nullable=True),
        sa.Column("source_end_char", sa.Integer(), nullable=True),
        sa.Column("source_json_path", sa.String(length=255), nullable=True),
        sa.Column("source_row_index", sa.Integer(), nullable=True),
        sa.Column("source_column_name", sa.String(length=180), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accepted_by", sa.String(length=120), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_extractions_id", "extractions", ["id"])
    op.create_index("ix_extractions_document_id", "extractions", ["document_id"])
    op.create_index("ix_extractions_field_definition_id", "extractions", ["field_definition_id"])
    op.create_index("ix_extractions_template_key", "extractions", ["template_key"])
    op.create_index("ix_extractions_standard_field_key", "extractions", ["standard_field_key"])

    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("extraction_id", sa.Integer(), sa.ForeignKey("extractions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=False),
        sa.Column("corrected_value", sa.Text(), nullable=False),
        sa.Column("corrected_by", sa.String(length=120), nullable=False, server_default="demo_user"),
        sa.Column("corrected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_corrections_id", "corrections", ["id"])
    op.create_index("ix_corrections_extraction_id", "corrections", ["extraction_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False, server_default="system"),
        sa.Column("details", sa.Text(), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_document_id", "audit_logs", ["document_id"])

    op.create_table(
        "document_ai_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("overall_confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("document_quality", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("review_recommendation", sa.Text(), nullable=False),
        sa.Column("issues_json", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("consistency_checks_json", sa.Text(), nullable=True, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_document_ai_reviews_id", "document_ai_reviews", ["id"])
    op.create_index("ix_document_ai_reviews_document_id", "document_ai_reviews", ["document_id"])

    op.create_table(
        "ai_request_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_type", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("cache_key", name="uq_ai_request_cache_cache_key"),
    )
    op.create_index("ix_ai_request_cache_id", "ai_request_cache", ["id"])
    op.create_index("ix_ai_request_cache_cache_key", "ai_request_cache", ["cache_key"])
    op.create_index("ix_ai_request_cache_content_hash", "ai_request_cache", ["content_hash"])

    op.create_table(
        "ai_rate_limit_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("window_type", sa.String(length=20), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "model", "window_type", "window_start", name="uq_ai_rate_window"),
    )
    op.create_index("ix_ai_rate_limit_windows_id", "ai_rate_limit_windows", ["id"])
    op.create_index("ix_ai_rate_limit_windows_provider", "ai_rate_limit_windows", ["provider"])
    op.create_index("ix_ai_rate_limit_windows_model", "ai_rate_limit_windows", ["model"])
    op.create_index("ix_ai_rate_limit_windows_window_type", "ai_rate_limit_windows", ["window_type"])
    op.create_index("ix_ai_rate_limit_windows_window_start", "ai_rate_limit_windows", ["window_start"])


def downgrade() -> None:
    op.drop_table("ai_rate_limit_windows")
    op.drop_table("ai_request_cache")
    op.drop_table("document_ai_reviews")
    op.drop_table("audit_logs")
    op.drop_table("corrections")
    op.drop_table("extractions")
    op.drop_table("processing_jobs")
    op.drop_table("field_definitions")
    op.drop_table("documents")
    op.drop_table("document_templates")
