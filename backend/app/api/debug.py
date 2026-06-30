from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AIRequestCache, AIRateLimitWindow, AuditLog, Correction, Document, DocumentAIReview, Extraction, ProcessingJob

router = APIRouter(prefix="/debug", tags=["debug"])

DEBUG_TABLE_MODELS = {
    "documents": Document,
    "processing_jobs": ProcessingJob,
    "extractions": Extraction,
    "corrections": Correction,
    "audit_logs": AuditLog,
    "document_ai_reviews": DocumentAIReview,
    "ai_request_cache": AIRequestCache,
    "ai_rate_limit_windows": AIRateLimitWindow,
}


def serialize_debug_row(row):
    data = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, (bytes, bytearray)):
            value = f"<{len(value)} bytes>"
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        data[column.name] = value
    return data


def apply_debug_search(stmt, model, q: str | None):
    if not q or not q.strip():
        return stmt
    term = f"%{q.strip()}%"
    conditions = []
    for column in model.__table__.columns:
        if str(column.type).lower().startswith(("varchar", "text")):
            conditions.append(column.ilike(term))
    if conditions:
        stmt = stmt.where(or_(*conditions))
    return stmt


@router.get("/tables")
def debug_tables():
    return [
        {"name": name, "columns": [column.name for column in model.__table__.columns]}
        for name, model in DEBUG_TABLE_MODELS.items()
    ]


@router.get("/tables/{table_name}")
def debug_table_rows(
    table_name: str,
    q: str | None = Query(default=None, description="Optional text search across text/varchar columns."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    model = DEBUG_TABLE_MODELS.get(table_name)
    if not model:
        raise HTTPException(status_code=404, detail="Unknown debug table")

    stmt = apply_debug_search(select(model), model, q)
    stmt = stmt.order_by(model.id.desc()).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()
    return {
        "table": table_name,
        "columns": [column.name for column in model.__table__.columns],
        "limit": limit,
        "offset": offset,
        "rows": [serialize_debug_row(row) for row in rows],
    }
