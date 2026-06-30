from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DocumentTemplate, FieldDefinition

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "document_templates"


@dataclass(slots=True)
class TemplateField:
    key: str
    label: str
    data_type: str = "string"
    required: bool = False
    aliases: list[str] | None = None
    validation: dict | None = None
    order: int = 0


@dataclass(slots=True)
class TemplateDefinition:
    key: str
    name: str
    industry: str
    description: str
    aliases: list[str]
    fields: list[TemplateField]


def _normalize_key(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def load_template_files() -> list[TemplateDefinition]:
    templates: list[TemplateDefinition] = []
    if not TEMPLATE_DIR.exists():
        return templates
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        fields: list[TemplateField] = []
        for idx, item in enumerate(data.get("fields", [])):
            fields.append(TemplateField(
                key=str(item["key"]),
                label=str(item.get("label") or item["key"]),
                data_type=str(item.get("data_type") or "string"),
                required=bool(item.get("required", False)),
                aliases=[str(alias) for alias in item.get("aliases", [])],
                validation=dict(item.get("validation", {})),
                order=idx,
            ))
        templates.append(TemplateDefinition(
            key=str(data["key"]),
            name=str(data.get("name") or data["key"]),
            industry=str(data.get("industry") or "general"),
            description=str(data.get("description") or ""),
            aliases=[str(alias) for alias in data.get("aliases", [])],
            fields=fields,
        ))
    return templates


def seed_document_templates(db: Session) -> None:
    """Seed bundled template JSON files into PostgreSQL idempotently."""
    for template in load_template_files():
        model = db.scalar(select(DocumentTemplate).where(DocumentTemplate.template_key == template.key))
        if not model:
            model = DocumentTemplate(template_key=template.key, name=template.name, industry=template.industry, description=template.description)
            db.add(model)
            db.flush()
        else:
            model.name = template.name
            model.industry = template.industry
            model.description = template.description

        existing = {field.field_key: field for field in db.scalars(select(FieldDefinition).where(FieldDefinition.template_id == model.id)).all()}
        for field in template.fields:
            aliases_json = json.dumps(field.aliases or [], ensure_ascii=False)
            validation_json = json.dumps(field.validation or {}, ensure_ascii=False)
            row = existing.get(field.key)
            if not row:
                row = FieldDefinition(template_id=model.id, field_key=field.key, display_label=field.label)
                db.add(row)
            row.display_label = field.label
            row.data_type = field.data_type
            row.required = field.required
            row.aliases_json = aliases_json
            row.validation_json = validation_json
            row.display_order = field.order
    db.commit()


def get_template_definition(template_key: str | None) -> TemplateDefinition | None:
    if not template_key or template_key == "auto":
        return None
    for template in load_template_files():
        if template.key == template_key:
            return template
    return None


def infer_template_key(text: str, parser_type: str, requested_key: str | None = None) -> str | None:
    if requested_key and requested_key != "auto":
        return requested_key
    lower = text.lower()
    if parser_type in {"json", "csv"}:
        return None
    best_key: str | None = None
    best_score = 0
    for template in load_template_files():
        terms = [template.name, template.key, template.industry, *template.aliases]
        score = sum(1 for term in terms if term and term.lower() in lower)
        for field in template.fields:
            score += sum(1 for alias in [field.label, field.key, *(field.aliases or [])] if alias and alias.lower().replace("_", " ") in lower)
        if score > best_score:
            best_score = score
            best_key = template.key
    return best_key if best_score >= 2 else None


def match_template_field(template: TemplateDefinition, field_name: str) -> TemplateField | None:
    normalized = _normalize_key(field_name)
    candidates = {normalized}

    # Structured rows often look like records[0].total_amount. Consider the
    # suffix after the row prefix as the business field name.
    if "." in field_name:
        candidates.add(_normalize_key(field_name.rsplit(".", 1)[-1]))
    if normalized.startswith("records_"):
        parts = normalized.split("_")
        if len(parts) >= 3 and parts[1].isdigit():
            candidates.add("_".join(parts[2:]))

    for field in template.fields:
        names = {_normalize_key(field.key), _normalize_key(field.label), *{_normalize_key(alias) for alias in (field.aliases or [])}}
        if candidates & names:
            return field
    return None


def _record_prefix(field_name: str) -> str | None:
    """Return records[n] prefix for structured rows, if present."""
    if field_name.startswith("records[") and "." in field_name:
        return field_name.rsplit(".", 1)[0]
    return None


def apply_template_to_fields(fields, template_key: str | None, field_factory: Callable[..., object] | None = None):
    """Enforce a selected template against raw extracted fields.

    In discovery mode, the system keeps flexible AI/deterministic fields.
    In template mode, the template is treated as a contract:
    - matched fields are canonicalized to the template field_key;
    - duplicate official fields are collapsed to the highest-confidence value;
    - missing required fields are created as review-required checklist rows;
    - unknown extracted fields are retained only as suggested_extra_fields.* rows and
      are not assigned a standard_field_key, so client queries stay clean.
    """
    template = get_template_definition(template_key)
    if not template:
        return fields, None, []

    official_by_identity: dict[str, object] = {}
    matched_required_keys: set[str] = set()
    suggestions: list[object] = []

    for field in fields:
        original_name = str(getattr(field, "field_name", ""))
        match = match_template_field(template, original_name)
        if match:
            matched_required_keys.add(match.key)
            prefix = _record_prefix(original_name)
            canonical_name = f"{prefix}.{match.key}" if prefix else match.key
            identity = canonical_name
            setattr(field, "field_name", canonical_name)
            setattr(field, "standard_field_key", match.key)
            setattr(field, "data_type", match.data_type)
            setattr(field, "required", match.required)
            setattr(field, "validation", match.validation or {})
            setattr(field, "template_key", template.key)
            existing = official_by_identity.get(identity)
            if existing is None or float(getattr(field, "confidence", 0.0)) > float(getattr(existing, "confidence", 0.0)):
                official_by_identity[identity] = field
            continue

        # Keep useful discovery output, but do not let it become part of the
        # company's official schema. These rows are visible as suggestions only.
        safe_name = _normalize_key(original_name or "unknown_field") or "unknown_field"
        setattr(field, "field_name", f"suggested_extra_fields.{safe_name}")
        setattr(field, "standard_field_key", None)
        setattr(field, "data_type", "suggestion")
        setattr(field, "required", False)
        setattr(field, "template_key", None)
        # Suggestions should not block template approval unless their confidence
        # is low enough for the global confidence rule to request review.
        setattr(field, "auto_accept", True)
        suggestions.append(field)

    missing_required = [field for field in template.fields if field.required and field.key not in matched_required_keys]
    missing_rows: list[object] = []
    if field_factory is None and fields:
        field_factory = type(fields[0])

    if field_factory is not None:
        for field in missing_required:
            missing = field_factory(
                field_name=field.key,
                value="",
                confidence=0.0,
                snippet="Required template field was not found in the extracted data.",
                reasoning=f'Required field from template "{template.name}" was missing and must be reviewed manually.',
                auto_accept=False,
            )
            setattr(missing, "standard_field_key", field.key)
            setattr(missing, "data_type", field.data_type)
            setattr(missing, "required", field.required)
            setattr(missing, "template_key", template.key)
            missing_rows.append(missing)

    order_by_key = {field.key: field.order for field in template.fields}

    def _record_sort_index(field_name: str) -> int:
        if field_name.startswith("records[") and "]" in field_name:
            try:
                return int(field_name.split("records[", 1)[1].split("]", 1)[0])
            except ValueError:
                return 0
        return 0

    def _template_sort_key(item) -> tuple[int, int, int, str]:
        name = str(getattr(item, "field_name", ""))
        standard_key = str(getattr(item, "standard_field_key", "") or name.rsplit(".", 1)[-1])
        is_record_row = 1 if name.startswith("records[") else 0
        return (is_record_row, _record_sort_index(name), order_by_key.get(standard_key, 9999), name)

    ordered_template_fields = sorted([*official_by_identity.values(), *missing_rows], key=_template_sort_key)
    return [*ordered_template_fields, *suggestions], template, missing_required


def template_prompt_contract(template_key: str | None) -> str:
    """Return concise template instructions for AI providers.

    The backend still enforces the template after the model responds; this
    contract simply improves extraction quality and reduces unknown field names.
    """
    template = get_template_definition(template_key)
    if not template:
        return ""
    lines = [
        f"Template extraction mode: {template.name} ({template.key}).",
        "Extract values only for these canonical field keys. Return null/empty if absent.",
    ]
    for field in template.fields:
        required = "required" if field.required else "optional"
        aliases = f" Aliases: {', '.join(field.aliases or [])}." if field.aliases else ""
        validation = f" Validation: {field.validation}." if field.validation else ""
        lines.append(f"- {field.key} ({field.data_type}, {required}): {field.label}.{aliases}{validation}")
    lines.append("Do not invent new official field names. If extra useful data appears, label it clearly as a suggested extra field.")
    return "\n".join(lines)


def template_response(template: TemplateDefinition) -> dict:
    return {
        "key": template.key,
        "name": template.name,
        "industry": template.industry,
        "description": template.description,
        "fields": [
            {"key": f.key, "label": f.label, "data_type": f.data_type, "required": f.required, "aliases": f.aliases or [], "validation": f.validation or {}}
            for f in template.fields
        ],
    }
