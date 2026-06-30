from __future__ import annotations

from fastapi import APIRouter

from ..schemas import DocumentTemplateOut
from ..services.template_service import load_template_files, template_response

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[DocumentTemplateOut])
def list_document_templates():
    """Return bundled configurable document type templates.

    Templates define standardized field keys clients can query consistently while
    still allowing the extraction table to store flexible AI/discovery fields.
    """
    return [template_response(template) for template in load_template_files()]
