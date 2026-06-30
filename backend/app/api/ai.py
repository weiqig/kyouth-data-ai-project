from __future__ import annotations

import os
from fastapi import APIRouter

from ..ai.service import AISettings

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/config")
def ai_config():
    """Return safe AI runtime configuration for debugging. Secrets are omitted."""
    settings = AISettings.from_env()
    return {
        "enabled": settings.enabled,
        "provider": settings.provider,
        "apply_to_parser_types": sorted(settings.apply_to_parser_types),
        "fallback_to_deterministic": settings.fallback_to_deterministic,
        "defer_on_rate_limit": settings.defer_on_rate_limit,
        "cache_enabled": os.getenv("AI_CACHE_ENABLED", "true"),
        "rate_limit_enabled": os.getenv("AI_RATE_LIMIT_ENABLED", "true"),
        "max_requests_per_minute": os.getenv("AI_MAX_REQUESTS_PER_MINUTE", "30"),
        "max_requests_per_day": os.getenv("AI_MAX_REQUESTS_PER_DAY", "1000"),
    }
