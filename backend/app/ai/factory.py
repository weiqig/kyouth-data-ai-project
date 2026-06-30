from __future__ import annotations

import os

from .base import AIProvider
from .providers import (
    AnthropicProvider,
    GeminiProvider,
    MockAIProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)


class AIFactory:
    """Build provider implementations from environment configuration."""

    @staticmethod
    def create(provider_name: str | None = None) -> AIProvider:
        provider = (provider_name or os.getenv("AI_PROVIDER", "mock")).strip().lower()
        timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "60"))

        if provider == "mock":
            return MockAIProvider(
                model=os.getenv("AI_MOCK_MODEL", "mock-extractor"),
                timeout_seconds=timeout,
            )

        if provider == "gemini":
            return GeminiProvider(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                api_key=os.getenv("GEMINI_API_KEY", ""),
                base_url=os.getenv(
                    "GEMINI_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta",
                ),
                timeout_seconds=timeout,
            )

        if provider in {"anthropic", "claude"}:
            return AnthropicProvider(
                model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                api_key=os.getenv("ANTHROPIC_API_KEY", ""),
                base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                timeout_seconds=timeout,
            )

        if provider == "ollama":
            return OllamaProvider(
                model=os.getenv("OLLAMA_MODEL", "llama3.1"),
                base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
                timeout_seconds=float(
                    os.getenv("OLLAMA_TIMEOUT_SECONDS", str(timeout))
                ),
            )

        if provider in {"openai_compatible", "openai-compatible", "gateway"}:
            return OpenAICompatibleProvider(
                model=os.getenv("OPENAI_COMPATIBLE_MODEL", "gpt-4o-mini"),
                api_key=os.getenv("OPENAI_COMPATIBLE_API_KEY", ""),
                base_url=os.getenv(
                    "OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8001"
                ),
                timeout_seconds=timeout,
            )

        raise ValueError(
            f"Unsupported AI_PROVIDER={provider!r}. Use mock, gemini, anthropic, ollama, or openai_compatible."
        )
