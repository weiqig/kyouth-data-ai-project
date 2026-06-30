from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..ai.controls import utcnow
from ..models import AuditLog, Document, DocumentStatus, JobStatus, ProcessingJob

DEFAULT_MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
DEFAULT_STALE_MINUTES = int(os.getenv("STALE_JOB_MINUTES", "10"))
DEFAULT_BATCH_SIZE = int(os.getenv("JOB_RECOVERY_BATCH_SIZE", "50"))
DEFAULT_PENDING_REQUEUE_GRACE_SECONDS = int(
    os.getenv("PENDING_JOB_REQUEUE_GRACE_SECONDS", "120")
)


@dataclass(frozen=True)
class RecoveryPlan:
    job_ids: list[int]
    count: int


def _mark_recovery_skip_rejected(
    db: Session, job: ProcessingJob, *, action: str
) -> None:
    job.status = JobStatus.FAILED.value
    job.error_message = "Recovery skipped: document is rejected."
    job.finished_at = utcnow()
    db.add(
        AuditLog(
            document_id=job.document_id,
            action=action,
            actor="celery_recovery",
            details=f"Job {job.id} was not requeued because the document is rejected.",
        )
    )


def _prepare_job_for_requeue(
    db: Session, job: ProcessingJob, *, action: str, details: str
) -> int | None:
    doc = db.get(Document, job.document_id)
    if not doc:
        job.status = JobStatus.FAILED.value
        job.error_message = "Recovery skipped: document no longer exists."
        job.finished_at = utcnow()
        return None
    if doc.status == DocumentStatus.REJECTED.value:
        _mark_recovery_skip_rejected(
            db, job, action=f"{action}_skipped_rejected_document"
        )
        return None

    job.status = JobStatus.QUEUED.value
    job.error_message = None
    job.finished_at = None
    doc.status = DocumentStatus.PENDING.value
    doc.error_message = None
    db.add(
        AuditLog(
            document_id=job.document_id,
            action=action,
            actor="celery_recovery",
            details=details,
        )
    )
    return job.id


def collect_deferred_jobs_ready_for_retry(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RecoveryPlan:
    """Find queued/deferred jobs whose AI quota window has elapsed."""
    jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.QUEUED.value)
        .where(ProcessingJob.deferred_reason.is_not(None))
        .where(ProcessingJob.attempts < max_attempts)
        .where(
            or_(
                ProcessingJob.next_retry_at.is_(None),
                ProcessingJob.next_retry_at <= func.now(),
            )
        )
        .order_by(
            ProcessingJob.next_retry_at.asc().nullsfirst(),
            ProcessingJob.created_at.asc(),
        )
        .limit(batch_size)
    ).all()

    job_ids: list[int] = []
    for job in jobs:
        job_id = _prepare_job_for_requeue(
            db,
            job,
            action="deferred_job_requeued",
            details=f"Deferred job {job.id} is ready for retry and was requeued by Celery recovery.",
        )
        if job_id is not None:
            job.deferred_reason = None
            job.next_retry_at = None
            job_ids.append(job_id)
    db.commit()
    return RecoveryPlan(job_ids=job_ids, count=len(job_ids))


def collect_stuck_processing_jobs(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    stale_minutes: int = DEFAULT_STALE_MINUTES,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RecoveryPlan:
    """Find jobs left running after a worker crash and requeue them."""
    cutoff = utcnow() - timedelta(minutes=stale_minutes)
    jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.RUNNING.value)
        .where(ProcessingJob.attempts < max_attempts)
        .where(ProcessingJob.started_at.is_not(None))
        .where(ProcessingJob.started_at < cutoff)
        .order_by(ProcessingJob.started_at.asc())
        .limit(batch_size)
    ).all()

    job_ids: list[int] = []
    for job in jobs:
        job_id = _prepare_job_for_requeue(
            db,
            job,
            action="stuck_processing_job_requeued",
            details=f"Running job {job.id} was stale for more than {stale_minutes} minutes and was reset to queued.",
        )
        if job_id is not None:
            job_ids.append(job_id)
    db.commit()
    return RecoveryPlan(job_ids=job_ids, count=len(job_ids))


def collect_orphaned_pending_jobs(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    grace_seconds: int = DEFAULT_PENDING_REQUEUE_GRACE_SECONDS,
) -> RecoveryPlan:
    """Requeue pending PostgreSQL jobs that may not exist in Redis anymore.

    Redis is treated as delivery infrastructure only. PostgreSQL job state remains
    the source of truth, so this task periodically recreates missing Celery
    messages for eligible queued jobs.
    """
    cutoff = utcnow() - timedelta(seconds=grace_seconds)
    jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.QUEUED.value)
        .where(ProcessingJob.deferred_reason.is_(None))
        .where(ProcessingJob.attempts < max_attempts)
        .where(ProcessingJob.created_at < cutoff)
        .where(
            or_(
                ProcessingJob.next_retry_at.is_(None),
                ProcessingJob.next_retry_at <= func.now(),
            )
        )
        .order_by(ProcessingJob.created_at.asc())
        .limit(batch_size)
    ).all()

    job_ids: list[int] = []
    for job in jobs:
        job_id = _prepare_job_for_requeue(
            db,
            job,
            action="pending_job_requeued",
            details=f"Queued job {job.id} was older than {grace_seconds} seconds and was requeued from PostgreSQL durable state.",
        )
        if job_id is not None:
            job_ids.append(job_id)
    db.commit()
    return RecoveryPlan(job_ids=job_ids, count=len(job_ids))


def collect_retryable_failed_jobs(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> RecoveryPlan:
    """Retry failed jobs that still have attempts remaining."""
    jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.FAILED.value)
        .where(ProcessingJob.attempts < max_attempts)
        .where(
            or_(
                ProcessingJob.next_retry_at.is_(None),
                ProcessingJob.next_retry_at <= func.now(),
            )
        )
        .order_by(
            ProcessingJob.finished_at.asc().nullsfirst(), ProcessingJob.created_at.asc()
        )
        .limit(batch_size)
    ).all()

    job_ids: list[int] = []
    for job in jobs:
        job_id = _prepare_job_for_requeue(
            db,
            job,
            action="failed_job_requeued",
            details=f"Failed job {job.id} still had attempts remaining and was requeued by Celery recovery.",
        )
        if job_id is not None:
            job.deferred_reason = None
            job.next_retry_at = None
            job_ids.append(job_id)
    db.commit()
    return RecoveryPlan(job_ids=job_ids, count=len(job_ids))
