from __future__ import annotations

import os
from dataclasses import dataclass

from .base import AIExtractionResult
from .factory import AIFactory


@dataclass(slots=True)
class AISettings:
    enabled: bool
    provider: str
    apply_to_parser_types: set[str]
    fallback_to_deterministic: bool
    defer_on_rate_limit: bool
    review_assistant_enabled: bool
    review_assistant_required: bool

    @classmethod
    def from_env(cls) -> "AISettings":
        apply_to = os.getenv(
            "AI_APPLY_TO_PARSER_TYPES", "raw_text,markdown,pdf_text"
        ).strip()
        return cls(
            enabled=os.getenv("AI_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            provider=os.getenv("AI_PROVIDER", "mock").strip().lower(),
            apply_to_parser_types={
                part.strip() for part in apply_to.split(",") if part.strip()
            },
            fallback_to_deterministic=os.getenv("AI_FALLBACK_TO_DETERMINISTIC", "true")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            defer_on_rate_limit=os.getenv("AI_DEFER_ON_RATE_LIMIT", "true")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            review_assistant_enabled=os.getenv("AI_REVIEW_ASSISTANT_ENABLED", "true")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            review_assistant_required=os.getenv("AI_REVIEW_ASSISTANT_REQUIRED", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
        )


def should_use_ai(parser_type: str, settings: AISettings | None = None) -> bool:
    settings = settings or AISettings.from_env()
    return settings.enabled and parser_type in settings.apply_to_parser_types


def extract_with_configured_ai(
    *, document_text: str, parser_type: str
) -> AIExtractionResult:
    provider = AIFactory.create()
    return provider.extract_fields(document_text=document_text, parser_type=parser_type)


def should_use_ai_review_assistant(settings: AISettings | None = None) -> bool:
    settings = settings or AISettings.from_env()
    return settings.enabled and settings.review_assistant_enabled


def review_with_configured_ai(*, review_context: str):
    provider = AIFactory.create()
    return provider.review_document(review_context=review_context)
