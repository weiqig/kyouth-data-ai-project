from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ValidationResult:
    status: str
    message: str
    rule: str
    requires_review: bool


def _is_empty(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _parse_float(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    if cleaned in {"", ".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _valid_date(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y"]
    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            pass
    return False


def validate_value(field_name: str, value: str | None, data_type: str | None, required: bool = False, validation: dict[str, Any] | None = None) -> ValidationResult:
    """Validate an extracted/reviewed value against a template field definition.

    This is intentionally deterministic and conservative: validation failures do
    not overwrite data, they simply mark the field as needing human review.
    """
    validation = validation or {}
    data_type = (data_type or "string").lower()
    label = field_name.replace("_", " ").title()

    if required and _is_empty(value):
        return ValidationResult("missing_required", f"{label} is required by the selected template but no value was found.", "required", True)
    if _is_empty(value):
        return ValidationResult("not_applicable", "Optional field is empty.", "optional_empty", False)

    text = str(value).strip()

    if data_type == "email":
        ok = bool(re.fullmatch(r"[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}", text))
        return ValidationResult("valid" if ok else "invalid", "Valid email address." if ok else "Value is not a valid email address.", "email", not ok)

    if data_type == "date":
        ok = _valid_date(text)
        return ValidationResult("valid" if ok else "invalid", "Valid date format." if ok else "Value is not a supported date format.", "date", not ok)

    if data_type == "currency":
        amount = _parse_float(text)
        allowed_currencies = validation.get("currencies") or ["RM", "MYR", "USD", "EUR", "GBP", "$"]
        has_currency = any(str(code).lower() in text.lower() for code in allowed_currencies)
        min_value = validation.get("min")
        ok = amount is not None and (has_currency or not validation.get("require_currency_symbol", False))
        if min_value is not None and amount is not None:
            ok = ok and amount >= float(min_value)
        if ok:
            return ValidationResult("valid", "Valid currency/amount value.", "currency", False)
        return ValidationResult("invalid", "Value is not a valid currency/amount for this template field.", "currency", True)

    if data_type == "currency_code":
        allowed = validation.get("allowed") or ["MYR", "RM", "USD", "EUR", "GBP", "SGD"]
        ok = text.upper() in {str(item).upper() for item in allowed}
        return ValidationResult("valid" if ok else "invalid", "Valid currency code." if ok else f"Currency code must be one of: {', '.join(map(str, allowed))}.", "currency_code", not ok)

    if data_type == "percentage":
        num = _parse_float(text)
        ok = num is not None and 0 <= num <= 100
        return ValidationResult("valid" if ok else "invalid", "Valid percentage between 0 and 100." if ok else "Percentage must be a number between 0 and 100.", "percentage", not ok)

    if data_type in {"number", "integer"}:
        num = _parse_float(text)
        ok = num is not None
        if data_type == "integer" and ok:
            ok = float(num).is_integer()
        return ValidationResult("valid" if ok else "invalid", "Valid numeric value." if ok else "Value must be numeric.", data_type, not ok)

    # Generic string validation.
    min_length = int(validation.get("min_length", 1 if required else 0))
    if len(text) < min_length:
        return ValidationResult("invalid", f"Value must contain at least {min_length} character(s).", "string_min_length", True)
    pattern = validation.get("pattern")
    if pattern and not re.search(str(pattern), text):
        return ValidationResult("invalid", "Value does not match the configured pattern.", "regex", True)
    return ValidationResult("valid", "Basic value check passed.", "string", False)
