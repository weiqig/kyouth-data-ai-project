from __future__ import annotations

import re
from typing import Callable

from .template_service import TemplateDefinition, get_template_definition


def _normalize_label(value: str) -> str:
    return " ".join((value or "").replace("_", " ").strip().lower().split())


def _label_variants(field) -> list[str]:
    """Return field labels/aliases ordered from most specific to least specific."""
    variants: list[str] = []
    for candidate in [field.label, field.key.replace("_", " "), *(field.aliases or [])]:
        normalized = _normalize_label(str(candidate))
        if normalized and normalized not in variants:
            variants.append(normalized)
    return sorted(variants, key=len, reverse=True)


def _line_value_for_label(line: str, label: str) -> tuple[str, int, int] | None:
    """Extract `value` from labelled lines such as `PO Number: PO-7788`.

    Matching is intentionally conservative: the label must appear at the start of
    the line, optionally preceded by bullet/list characters, and must be followed
    by a common key-value separator. This avoids broad aliases such as `date`
    accidentally matching unrelated phrases inside a sentence.
    """
    escaped = re.escape(label).replace(r"\ ", r"[\s_\-]+")
    pattern = re.compile(
        rf"^\s*(?:[-*•]\s*)?(?:\d+[.)]\s*)?{escaped}\s*(?::|=|\-|–|—)\s*(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )
    match = pattern.match(line)
    if not match:
        return None
    raw_value = match.group("value")
    value = raw_value.strip().strip('"').strip("'").strip()
    if not value:
        return None
    value_start = match.start("value") + len(raw_value) - len(raw_value.lstrip())
    value_end = value_start + len(value)
    return value, value_start, value_end


def extract_template_labelled_fields(
    text: str,
    template_key: str | None,
    field_factory: Callable[..., object],
) -> tuple[list[object], TemplateDefinition | None]:
    """Extract obvious labelled key-value pairs using a selected template.

    This deterministic layer runs before AI in template mode. It is designed for
    common business documents where fields are explicitly labelled, for example:

        PO Number: PO-7788
        Project Name: Klang Warehouse Extension

    The AI remains useful for ambiguous prose, but clean labelled fields should
    not require an LLM call to be captured correctly.
    """
    template = get_template_definition(template_key)
    if not template or not text.strip():
        return [], template

    lines_with_locations: list[tuple[int, int, str]] = []
    offset = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped:
            leading_ws = len(raw_line) - len(raw_line.lstrip())
            lines_with_locations.append((line_number, offset + leading_ws, stripped))
        offset += len(raw_line) + 1
    extracted: list[object] = []
    seen_keys: set[str] = set()

    for field in template.fields:
        for line_number, line_start, line in lines_with_locations:
            if field.key in seen_keys:
                break
            for label in _label_variants(field):
                match_result = _line_value_for_label(line, label)
                if match_result is None:
                    continue
                value, value_start_in_line, value_end_in_line = match_result
                item = field_factory(
                    field_name=field.key,
                    value=value,
                    confidence=0.98,
                    snippet=line[:500],
                    reasoning=f'Deterministically extracted from labelled source line using template label/alias "{label}".',
                    auto_accept=True,
                    source_line_number=line_number,
                    source_start_char=line_start + value_start_in_line,
                    source_end_char=line_start + value_end_in_line,
                )
                setattr(item, "standard_field_key", field.key)
                setattr(item, "template_key", template.key)
                setattr(item, "data_type", field.data_type)
                setattr(item, "required", field.required)
                setattr(item, "validation", field.validation or {})
                extracted.append(item)
                seen_keys.add(field.key)
                break

    return extracted, template


def required_field_keys(template: TemplateDefinition | None) -> set[str]:
    if not template:
        return set()
    return {field.key for field in template.fields if field.required}
