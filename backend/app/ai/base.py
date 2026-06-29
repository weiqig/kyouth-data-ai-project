from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AIExtractedField:
    field_name: str
    value: str
    confidence: float
    source_snippet: str
    explanation: str


@dataclass(slots=True)
class AIExtractionResult:
    provider: str
    model: str
    fields: list[AIExtractedField]
    raw_response: str | None = None


class AIProvider(ABC):
    """Provider-agnostic extraction interface.

    Implementations may call Gemini, Claude, Ollama, OpenAI-compatible
    endpoints, or any future model provider. The rest of the app only depends
    on this abstract contract.
    """

    provider_name: str

    def __init__(self, model: str, timeout_seconds: float = 60.0) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def extract_fields(self, *, document_text: str, parser_type: str) -> AIExtractionResult:
        """Extract reviewable fields from unstructured text."""


def normalize_ai_fields(raw_fields: Any) -> list[AIExtractedField]:
    """Validate provider output into the app's common field structure."""
    if not isinstance(raw_fields, list):
        return []

    fields: list[AIExtractedField] = []
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field_name") or item.get("name") or "").strip()
        value = item.get("value", item.get("extracted_value", ""))
        if value is None:
            value = ""
        value = str(value).strip()
        if not field_name or not value:
            continue

        try:
            confidence = float(item.get("confidence", item.get("confidence_score", 0.7)))
        except (TypeError, ValueError):
            confidence = 0.7
        if confidence > 1:
            confidence = confidence / 100
        confidence = max(0.0, min(1.0, confidence))

        snippet = str(item.get("source_snippet") or item.get("snippet") or value).strip()
        explanation = str(item.get("explanation") or item.get("reasoning") or "Extracted by configured AI provider.").strip()
        fields.append(AIExtractedField(
            field_name=field_name[:120],
            value=value,
            confidence=round(confidence, 4),
            source_snippet=snippet[:1000],
            explanation=explanation[:1000],
        ))
    return fields
