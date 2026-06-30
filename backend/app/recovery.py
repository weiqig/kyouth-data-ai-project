from __future__ import annotations

from sqlalchemy.orm import Session

from .db import SessionLocal
from .services.job_recovery_service import (
    collect_deferred_jobs_ready_for_retry,
    collect_orphaned_pending_jobs,
    collect_retryable_failed_jobs,
    collect_stuck_processing_jobs,
)


def enqueue_recoverable_jobs(db: Session) -> dict[str, int]:
    """Compatibility helper used by manual development endpoints.

    Celery periodic tasks now own recovery/retry workflows. This helper performs
    the same database scan and then dispatches the returned jobs through Celery.
    """
    from .tasks import process_document_job

    totals = {
        "deferred_requeued": 0,
        "stuck_requeued": 0,
        "pending_requeued": 0,
        "failed_requeued": 0,
    }
    for key, collector in [
        ("deferred_requeued", collect_deferred_jobs_ready_for_retry),
        ("stuck_requeued", collect_stuck_processing_jobs),
        ("pending_requeued", collect_orphaned_pending_jobs),
        ("failed_requeued", collect_retryable_failed_jobs),
    ]:
        plan = collector(db)
        for job_id in plan.job_ids:
            process_document_job.delay(job_id)
        totals[key] = plan.count
    totals["total_requeued"] = sum(totals.values())
    return totals


def enqueue_recoverable_jobs_with_new_session() -> dict[str, int]:
    db = SessionLocal()
    try:
        return enqueue_recoverable_jobs(db)
    finally:
        db.close()
