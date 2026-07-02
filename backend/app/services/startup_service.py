from __future__ import annotations

from ..db import SessionLocal
from .template_service import seed_document_templates


def seed_startup_data() -> None:
    """Seed idempotent application data after Alembic migrations have created the schema."""
    db = SessionLocal()
    try:
        seed_document_templates(db)
    finally:
        db.close()
