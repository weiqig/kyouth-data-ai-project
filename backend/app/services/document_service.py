from __future__ import annotations

from sqlalchemy.orm import selectinload
from ..models import Document, Extraction
from .template_service import get_template_definition

LOAD_OPTIONS = (
    selectinload(Document.extractions).selectinload(Extraction.corrections),
    selectinload(Document.jobs),
    selectinload(Document.ai_reviews),
)


def _record_sort_index(field_name: str) -> int:
    if field_name.startswith("records[") and "]" in field_name:
        try:
            return int(field_name.split("records[", 1)[1].split("]", 1)[0])
        except ValueError:
            return 0
    return 0


def sort_document_extractions(document: Document | None) -> Document | None:
    """Order extracted fields consistently for API responses.

    Template documents behave like a checklist: official template fields follow
    the template's configured display order, including empty missing-required
    rows. Suggested extras and manually added custom fields come afterwards.

    Discovery documents preserve extraction/source order using insertion id as a
    stable fallback, which generally mirrors the original text/structured input
    order used by the parser.
    """
    if document is None or not getattr(document, "extractions", None):
        return document

    template = get_template_definition(document.document_type_key)
    if not template:
        document.extractions = sorted(
            document.extractions, key=lambda item: item.id or 0
        )
        return document

    order_by_key = {field.key: field.order for field in template.fields}

    def category(item: Extraction) -> int:
        if item.standard_field_key:
            return 0
        if item.field_name.startswith("suggested_extra_fields."):
            return 1
        if "Manually added by reviewer" in (item.ai_reasoning or ""):
            return 2
        return 3

    def sort_key(item: Extraction) -> tuple[int, int, int, int, str]:
        field_key = item.standard_field_key or item.field_name.rsplit(".", 1)[-1]
        return (
            category(item),
            _record_sort_index(item.field_name),
            order_by_key.get(field_key, 9999),
            item.id or 0,
            item.field_name,
        )

    document.extractions = sorted(document.extractions, key=sort_key)
    return document
