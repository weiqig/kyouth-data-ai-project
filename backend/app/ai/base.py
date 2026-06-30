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


@dataclass(slots=True)
class AIDocumentReviewResult:
    provider: str
    model: str
    summary: str
    overall_confidence: float
    document_quality: str
    review_recommendation: str
    issues: list[str]
    consistency_checks: list[str]
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

    @abstractmethod
    def review_document(self, *, review_context: str) -> AIDocumentReviewResult:
        """Produce a reviewer briefing from document text, fields, and validation results."""


def normalize_ai_review(raw: Any, *, provider: str, model: str, raw_response: str | None = None) -> AIDocumentReviewResult:
    if not isinstance(raw, dict):
        raw = {}
    summary = str(raw.get("summary") or "No AI review summary was returned.").strip()[:2000]
    quality = str(raw.get("document_quality") or raw.get("quality") or "unknown").strip().lower().replace(" ", "_")[:80]
    recommendation = str(raw.get("review_recommendation") or raw.get("recommendation") or "Review the extracted fields and validation messages before approval.").strip()[:2000]
    try:
        confidence = float(raw.get("overall_confidence", raw.get("confidence", 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence > 1:
        confidence = confidence / 100
    confidence = max(0.0, min(1.0, confidence))

    def as_str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip()[:500] for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()[:500]]
        return []

    return AIDocumentReviewResult(
        provider=provider,
        model=model,
        summary=summary,
        overall_confidence=round(confidence, 4),
        document_quality=quality or "unknown",
        review_recommendation=recommendation,
        issues=as_str_list(raw.get("issues") or raw.get("potential_issues")),
        consistency_checks=as_str_list(raw.get("consistency_checks")),
        raw_response=raw_response,
    )


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
