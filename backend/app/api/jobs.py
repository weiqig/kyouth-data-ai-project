from __future__ import annotations

from fastapi import APIRouter

from ..tasks import run_job_recovery

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/recover")
def request_job_recovery():
    """User-triggered recovery request for development/demo use.

    The API does not inspect or mutate job rows directly. It schedules the same
    Celery recovery workflow that Celery Beat runs periodically.
    """
    run_job_recovery.delay()
    return {
        "scheduled": True,
        "message": "Celery job recovery has been scheduled. Check audit logs or processing_jobs for results.",
    }


@router.post("/requeue-pending")
def requeue_pending_jobs():
    """Backward-compatible alias for older frontend/dev calls."""
    return request_job_recovery()
