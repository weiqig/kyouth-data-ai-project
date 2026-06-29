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

    @classmethod
    def from_env(cls) -> "AISettings":
        apply_to = os.getenv("AI_APPLY_TO_PARSER_TYPES", "raw_text,markdown,pdf_text").strip()
        return cls(
            enabled=os.getenv("AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            provider=os.getenv("AI_PROVIDER", "mock").strip().lower(),
            apply_to_parser_types={part.strip() for part in apply_to.split(",") if part.strip()},
            fallback_to_deterministic=os.getenv("AI_FALLBACK_TO_DETERMINISTIC", "true").strip().lower() in {"1", "true", "yes", "on"},
        )


def should_use_ai(parser_type: str, settings: AISettings | None = None) -> bool:
    settings = settings or AISettings.from_env()
    return settings.enabled and parser_type in settings.apply_to_parser_types


def extract_with_configured_ai(*, document_text: str, parser_type: str) -> AIExtractionResult:
    provider = AIFactory.create()
    return provider.extract_fields(document_text=document_text, parser_type=parser_type)
