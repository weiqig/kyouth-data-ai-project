from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AIRateLimitWindow, AIRequestCache
from .base import AIExtractedField, AIExtractionResult


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class AIRateLimitExceeded(RuntimeError):
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        window_type: str,
        limit: int,
        reset_at: datetime,
    ) -> None:
        self.provider = provider
        self.model = model
        self.window_type = window_type
        self.limit = limit
        self.reset_at = reset_at
        self.reset_after_seconds = max(60, int((reset_at - utcnow()).total_seconds()))
        super().__init__(
            f"AI {window_type} request limit reached for {provider}/{model}: "
            f"{limit} request(s). Next retry after {reset_at.isoformat()}."
        )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def ai_cache_key(
    *, content_hash: str, parser_type: str, provider: str, model: str
) -> str:
    raw = f"{content_hash}:{parser_type}:{provider}:{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_enabled() -> bool:
    return os.getenv("AI_CACHE_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def rate_limits_enabled() -> bool:
    return os.getenv("AI_RATE_LIMIT_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def minute_limit() -> int:
    return _env_int("AI_MAX_REQUESTS_PER_MINUTE", 30)


def day_limit() -> int:
    return _env_int("AI_MAX_REQUESTS_PER_DAY", 1000)


def retry_padding_seconds() -> int:
    return _env_int("AI_RATE_LIMIT_RETRY_PADDING_SECONDS", 5)


def _window_start(now: datetime, window_type: str) -> datetime:
    if window_type == "minute":
        return now.replace(second=0, microsecond=0)
    if window_type == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unknown rate-limit window type: {window_type}")


def _window_reset(start: datetime, window_type: str) -> datetime:
    if window_type == "minute":
        return start + timedelta(minutes=1, seconds=retry_padding_seconds())
    if window_type == "day":
        return start + timedelta(days=1, seconds=retry_padding_seconds())
    raise ValueError(f"Unknown rate-limit window type: {window_type}")


def _get_or_create_window(
    db: Session,
    *,
    provider: str,
    model: str,
    window_type: str,
    limit: int,
    now: datetime,
) -> AIRateLimitWindow:
    start = _window_start(now, window_type)
    row = db.scalar(
        select(AIRateLimitWindow)
        .where(
            AIRateLimitWindow.provider == provider,
            AIRateLimitWindow.model == model,
            AIRateLimitWindow.window_type == window_type,
            AIRateLimitWindow.window_start == start,
        )
        .with_for_update()
    )
    if row is None:
        row = AIRateLimitWindow(
            provider=provider,
            model=model,
            window_type=window_type,
            window_start=start,
            request_count=0,
            limit_count=limit,
        )
        db.add(row)
        db.flush()
    row.limit_count = limit
    return row


def reserve_ai_request_quota(db: Session, *, provider: str, model: str) -> None:
    """Reserve one provider request across minute/day windows.

    A limit <= 0 disables that specific window. This reservation happens before
    the external call so concurrent workers coordinate through PostgreSQL.
    """
    if not rate_limits_enabled():
        return

    now = utcnow()
    windows: list[tuple[str, int]] = [("minute", minute_limit()), ("day", day_limit())]
    rows: list[AIRateLimitWindow] = []
    for window_type, limit in windows:
        if limit <= 0:
            continue
        row = _get_or_create_window(
            db,
            provider=provider,
            model=model,
            window_type=window_type,
            limit=limit,
            now=now,
        )
        if row.request_count >= limit:
            raise AIRateLimitExceeded(
                provider=provider,
                model=model,
                window_type=window_type,
                limit=limit,
                reset_at=_window_reset(row.window_start, window_type),
            )
        rows.append(row)

    for row in rows:
        row.request_count += 1


def load_cached_ai_result(db: Session, *, cache_key: str) -> AIExtractionResult | None:
    if not cache_enabled():
        return None
    cache = db.scalar(
        select(AIRequestCache).where(AIRequestCache.cache_key == cache_key)
    )
    if not cache:
        return None
    try:
        payload = json.loads(cache.fields_json)
        fields = [AIExtractedField(**item) for item in payload]
    except Exception:  # noqa: BLE001
        return None
    cache.use_count += 1
    cache.last_used_at = utcnow()
    return AIExtractionResult(
        provider=cache.provider,
        model=cache.model,
        fields=fields,
        raw_response=cache.raw_response,
    )


def save_ai_result_to_cache(
    db: Session,
    *,
    cache_key: str,
    content_hash: str,
    parser_type: str,
    result: AIExtractionResult,
) -> None:
    if not cache_enabled():
        return
    existing = db.scalar(
        select(AIRequestCache).where(AIRequestCache.cache_key == cache_key)
    )
    fields_json = json.dumps(
        [asdict(field) for field in result.fields], ensure_ascii=False
    )
    if existing:
        existing.fields_json = fields_json
        existing.raw_response = result.raw_response
        existing.last_used_at = utcnow()
        existing.use_count += 1
        return
    db.add(
        AIRequestCache(
            cache_key=cache_key,
            content_hash=content_hash,
            parser_type=parser_type,
            provider=result.provider,
            model=result.model,
            fields_json=fields_json,
            raw_response=result.raw_response,
            use_count=1,
        )
    )
