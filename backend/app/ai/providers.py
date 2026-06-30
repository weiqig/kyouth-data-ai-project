from __future__ import annotations

import os
from typing import Any

import httpx

from .base import AIExtractionResult, AIProvider, normalize_ai_fields, normalize_ai_review
from .json_utils import parse_json_object
from .prompts import (
    SYSTEM_PROMPT,
    REVIEW_ASSISTANT_SYSTEM_PROMPT,
    build_extraction_prompt,
    build_review_assistant_prompt,
)


class MockAIProvider(AIProvider):
    provider_name = "mock"

    def extract_fields(self, *, document_text: str, parser_type: str) -> AIExtractionResult:
        lines = [line.strip() for line in document_text.splitlines() if line.strip()]
        summary = " ".join(lines[:3])[:300] if lines else document_text[:300]
        fields = normalize_ai_fields([
            {
                "field_name": "document_type",
                "value": "ai_mock_general_document",
                "confidence": 0.55,
                "source_snippet": document_text[:200],
                "explanation": "Mock provider used because no external AI provider is configured.",
            },
            {
                "field_name": "summary",
                "value": summary or "No readable content found.",
                "confidence": 0.55,
                "source_snippet": summary[:200] if summary else document_text[:200],
                "explanation": "Mock extractive summary for local development.",
            },
        ])
        return AIExtractionResult(provider=self.provider_name, model=self.model, fields=fields, raw_response=None)

    def review_document(self, *, review_context: str):
        missing = [line for line in review_context.splitlines() if "missing" in line.lower() or "needs_review" in line.lower()]
        raw = {
            "summary": "Mock AI review generated for local development. The document has been processed and should be checked against extracted fields, validation results, and template requirements.",
            "overall_confidence": 0.62,
            "document_quality": "needs_review" if missing else "unknown",
            "issues": missing[:5] or ["Mock provider cannot perform semantic review; configure Gemini/Claude/Ollama for real analysis."],
            "consistency_checks": ["No real semantic consistency check was performed by the mock provider."],
            "review_recommendation": "Use this mock briefing only for workflow testing. Human review is still required for business decisions.",
        }
        return normalize_ai_review(raw, provider=self.provider_name, model=self.model)


class GeminiProvider(AIProvider):
    provider_name = "gemini"

    def __init__(self, model: str, api_key: str, base_url: str, timeout_seconds: float = 60.0) -> None:
        super().__init__(model, timeout_seconds)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required when AI_PROVIDER=gemini.")
        url = f"{self.base_url}/models/{self.model}:generateContent"
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": float(os.getenv("AI_TEMPERATURE", "0.1")),
                "response_mime_type": "application/json",
            },
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, params={"key": self.api_key}, json=payload)
            response.raise_for_status()
            data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return "{}"
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))

    def extract_fields(self, *, document_text: str, parser_type: str) -> AIExtractionResult:
        text = self._generate_json(system_prompt=SYSTEM_PROMPT, user_prompt=build_extraction_prompt(document_text, parser_type))
        parsed = parse_json_object(text)
        return AIExtractionResult(self.provider_name, self.model, normalize_ai_fields(parsed.get("fields")), text)

    def review_document(self, *, review_context: str):
        text = self._generate_json(system_prompt=REVIEW_ASSISTANT_SYSTEM_PROMPT, user_prompt=build_review_assistant_prompt(review_context))
        return normalize_ai_review(parse_json_object(text), provider=self.provider_name, model=self.model, raw_response=text)


class AnthropicProvider(AIProvider):
    provider_name = "anthropic"

    def __init__(self, model: str, api_key: str, base_url: str, timeout_seconds: float = 60.0) -> None:
        super().__init__(model, timeout_seconds)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _message_json(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic.")
        payload = {
            "model": self.model,
            "max_tokens": int(os.getenv("AI_MAX_TOKENS", "2048")),
            "temperature": float(os.getenv("AI_TEMPERATURE", "0.1")),
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
            "content-type": "application/json",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/v1/messages", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data.get("content") or []
        return "".join(str(block.get("text", "")) for block in content if isinstance(block, dict))

    def extract_fields(self, *, document_text: str, parser_type: str) -> AIExtractionResult:
        text = self._message_json(system_prompt=SYSTEM_PROMPT, user_prompt=build_extraction_prompt(document_text, parser_type))
        parsed = parse_json_object(text)
        return AIExtractionResult(self.provider_name, self.model, normalize_ai_fields(parsed.get("fields")), text)

    def review_document(self, *, review_context: str):
        text = self._message_json(system_prompt=REVIEW_ASSISTANT_SYSTEM_PROMPT, user_prompt=build_review_assistant_prompt(review_context))
        return normalize_ai_review(parse_json_object(text), provider=self.provider_name, model=self.model, raw_response=text)


class OllamaProvider(AIProvider):
    provider_name = "ollama"

    def __init__(self, model: str, base_url: str, timeout_seconds: float = 120.0) -> None:
        super().__init__(model, timeout_seconds)
        self.base_url = base_url.rstrip("/")

    def _chat_json(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": float(os.getenv("AI_TEMPERATURE", "0.1"))},
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return str((data.get("message") or {}).get("content") or "")

    def extract_fields(self, *, document_text: str, parser_type: str) -> AIExtractionResult:
        text = self._chat_json(system_prompt=SYSTEM_PROMPT, user_prompt=build_extraction_prompt(document_text, parser_type))
        parsed = parse_json_object(text)
        return AIExtractionResult(self.provider_name, self.model, normalize_ai_fields(parsed.get("fields")), text)

    def review_document(self, *, review_context: str):
        text = self._chat_json(system_prompt=REVIEW_ASSISTANT_SYSTEM_PROMPT, user_prompt=build_review_assistant_prompt(review_context))
        return normalize_ai_review(parse_json_object(text), provider=self.provider_name, model=self.model, raw_response=text)


class OpenAICompatibleProvider(AIProvider):
    """Generic provider for OpenAI-compatible chat completion APIs."""

    provider_name = "openai_compatible"

    def __init__(self, model: str, api_key: str, base_url: str, timeout_seconds: float = 60.0) -> None:
        super().__init__(model, timeout_seconds)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _chat_json(self, *, system_prompt: str, user_prompt: str) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": float(os.getenv("AI_TEMPERATURE", "0.1")),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data["choices"][0]["message"]["content"])

    def extract_fields(self, *, document_text: str, parser_type: str) -> AIExtractionResult:
        text = self._chat_json(system_prompt=SYSTEM_PROMPT, user_prompt=build_extraction_prompt(document_text, parser_type))
        parsed = parse_json_object(text)
        return AIExtractionResult(self.provider_name, self.model, normalize_ai_fields(parsed.get("fields")), text)

    def review_document(self, *, review_context: str):
        text = self._chat_json(system_prompt=REVIEW_ASSISTANT_SYSTEM_PROMPT, user_prompt=build_review_assistant_prompt(review_context))
        return normalize_ai_review(parse_json_object(text), provider=self.provider_name, model=self.model, raw_response=text)
