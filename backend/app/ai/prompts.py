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


REVIEW_ASSISTANT_SYSTEM_PROMPT = """You are an audit-ready AI document review assistant.
Analyze the original document, extracted fields, template requirements, and validation results.
Return only valid JSON with this exact shape:
{
  "summary": "brief user-facing business summary of the document",
  "overall_confidence": 0.0,
  "document_quality": "good | needs_review | poor | unknown",
  "issues": ["concise issue for reviewer"],
  "consistency_checks": ["concise consistency observation"],
  "review_recommendation": "clear recommendation for the human reviewer"
}
Rules:
- Do not approve or reject the document.
- Do not invent missing values.
- Do not include chain-of-thought.
- Mention missing required fields and validation failures when present.
- Keep the response concise and useful for a reviewer.
"""


def build_review_assistant_prompt(review_context: str, max_chars: int = 14000) -> str:
    return f"""Review this processed document package and produce a reviewer briefing.

Context:
---
{review_context[:max_chars]}
---

Return JSON only."""
