from __future__ import annotations

from sqlalchemy import text

from . import models
from .db import Base, SessionLocal, engine
from .services.template_service import seed_document_templates


def ensure_runtime_schema() -> None:
    """Prepare the local prototype schema and seed bundled templates."""
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS accepted BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS accepted_by VARCHAR(120)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP WITH TIME ZONE"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS field_definition_id INTEGER"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS template_key VARCHAR(120)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS standard_field_key VARCHAR(120)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS data_type VARCHAR(80)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS required BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS validation_status VARCHAR(50)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS validation_message TEXT"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS validation_rule TEXT"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS source_line_number INTEGER"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS source_start_char INTEGER"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS source_end_char INTEGER"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS source_json_path VARCHAR(255)"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS source_row_index INTEGER"))
        conn.execute(text("ALTER TABLE extractions ADD COLUMN IF NOT EXISTS source_column_name VARCHAR(180)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_extractions_standard_field_key ON extractions (standard_field_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_extractions_template_key ON extractions (template_key)"))

        conn.execute(text("ALTER TABLE field_definitions ADD COLUMN IF NOT EXISTS validation_json TEXT"))

        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_file_data BYTEA"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_file_size INTEGER"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type_key VARCHAR(120)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type_label VARCHAR(180)"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS extraction_mode VARCHAR(50) NOT NULL DEFAULT 'auto_detect'"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS deferred_reason TEXT"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP WITH TIME ZONE"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_document_type_key ON documents (document_type_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_extraction_mode ON documents (extraction_mode)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)"))

        conn.execute(text("ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS deferred_reason TEXT"))
        conn.execute(text("ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP WITH TIME ZONE"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS document_ai_reviews (
                id SERIAL PRIMARY KEY,
                document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
                provider VARCHAR(80) NOT NULL,
                model VARCHAR(160) NOT NULL,
                summary TEXT NOT NULL,
                overall_confidence DOUBLE PRECISION DEFAULT 0.0,
                document_quality VARCHAR(80) DEFAULT 'unknown',
                review_recommendation TEXT NOT NULL,
                issues_json TEXT DEFAULT '[]',
                consistency_checks_json TEXT DEFAULT '[]',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_document_ai_reviews_document_id ON document_ai_reviews (document_id)"))

    db = SessionLocal()
    try:
        seed_document_templates(db)
    finally:
        db.close()
