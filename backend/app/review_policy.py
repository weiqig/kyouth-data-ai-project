from __future__ import annotations

import os

DEFAULT_CONFIDENCE_REVIEW_THRESHOLD = 0.80


def confidence_review_threshold() -> float:
    """Return the AI/extraction confidence threshold below which review is mandatory.

    Value is configured as a 0..1 fraction through AI_CONFIDENCE_REVIEW_THRESHOLD.
    For convenience, values above 1 are treated as percentages, so 80 means 0.80.
    """
    raw = os.getenv("AI_CONFIDENCE_REVIEW_THRESHOLD", str(DEFAULT_CONFIDENCE_REVIEW_THRESHOLD)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = DEFAULT_CONFIDENCE_REVIEW_THRESHOLD
    if value > 1:
        value = value / 100
    return max(0.0, min(1.0, value))


def requires_confidence_review(confidence_score: float | None) -> bool:
    """True when a field must remain review-required due to low confidence."""
    try:
        confidence = float(confidence_score or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence < confidence_review_threshold()
