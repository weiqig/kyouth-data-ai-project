from __future__ import annotations

SYSTEM_PROMPT = """You are an audit-ready information extraction engine.
Extract meaningful business fields from the supplied document.
Return only valid JSON with this exact shape:
{
  "fields": [
    {
      "field_name": "snake_case_name",
      "value": "extracted value as text",
      "confidence": 0.0,
      "source_snippet": "short exact supporting snippet from the document",
      "explanation": "brief user-facing explanation of why this field was extracted"
    }
  ]
}
Rules:
- Do not invent values.
- Do not include chain-of-thought.
- Use concise field names.
- Include document_type and summary when useful.
- Confidence must be between 0 and 1.
- If no reliable fields exist, return an empty fields array.
"""


def build_extraction_prompt(document_text: str, parser_type: str, max_chars: int = 12000) -> str:
    truncated = document_text[:max_chars]
    return f"""Parser type: {parser_type}

Document text:
---
{truncated}
---

Extract the fields now. Return JSON only."""
