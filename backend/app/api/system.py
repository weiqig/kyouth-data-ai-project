from __future__ import annotations

from fastapi import APIRouter

from ..parsers import SUPPORTED_CONTENT_TYPES, SUPPORTED_EXTENSIONS
from ..schemas import CapabilityOut

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"ok": True, "architecture": "postgres-state-driven"}


@router.get("/capabilities", response_model=CapabilityOut)
def capabilities():
    return {
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "supported_content_types": sorted(SUPPORTED_CONTENT_TYPES),
        "intentionally_deferred": [
            "scanned PDFs and image OCR",
            "Office files such as docx/xlsx/pptx",
            "email files and archives",
            "vector search and advanced auth",
        ],
    }
