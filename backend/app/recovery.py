from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import AuditLog, Document, DocumentStatus, JobStatus, ProcessingJob

DEFAULT_MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
DEFAULT_STALE_MINUTES = int(os.getenv("STALE_JOB_MINUTES", "10"))


def enqueue_recoverable_jobs(
    db: Session,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    stale_minutes: int = DEFAULT_STALE_MINUTES,
    include_failed: bool = True,
) -> dict[str, int]:
    """Requeue durable PostgreSQL jobs that Redis/Celery may have lost.

    PostgreSQL remains the source of truth. Redis only receives the job id again.
    This intentionally does not process work inline; it only recreates missing queue
    messages for jobs that are still eligible to run.
    """
    from .tasks import process_document_job  # local import avoids Celery app cycles

    statuses = [JobStatus.QUEUED.value]
    if include_failed:
        statuses.append(JobStatus.FAILED.value)

    jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.status.in_(statuses))
        .where(ProcessingJob.attempts < max_attempts)
        .order_by(ProcessingJob.created_at.asc())
    ).all()

    requeued = 0
    for job in jobs:
        doc = db.get(Document, job.document_id)
        if not doc:
            job.status = JobStatus.FAILED.value
            job.error_message = "Recovery skipped: document no longer exists."
            continue
        if job.status == JobStatus.FAILED.value:
            job.status = JobStatus.QUEUED.value
            job.error_message = None
            doc.status = DocumentStatus.PENDING.value
        db.add(AuditLog(
            document_id=job.document_id,
            action="job_requeued",
            actor="recovery",
            details=f"Recoverable job {job.id} was requeued from PostgreSQL state.",
        ))
        process_document_job.delay(job.id)
        requeued += 1

    # Recover workers that crashed after marking a job running.
    # PostgreSQL/SQLAlchemy interval syntax differs by database, so this project
    # uses PostgreSQL explicitly, matching the chosen architecture.
    stale_jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.RUNNING.value)
        .where(ProcessingJob.attempts < max_attempts)
        .where(ProcessingJob.started_at < func.now() - text(f"INTERVAL '{stale_minutes} minutes'"))
        .order_by(ProcessingJob.started_at.asc())
    ).all()

    stale_requeued = 0
    for job in stale_jobs:
        doc = db.get(Document, job.document_id)
        job.status = JobStatus.QUEUED.value
        job.error_message = f"Recovered from stale running state after {stale_minutes} minutes."
        if doc:
            doc.status = DocumentStatus.PENDING.value
        db.add(AuditLog(
            document_id=job.document_id,
            action="stale_job_requeued",
            actor="recovery",
            details=f"Stale running job {job.id} was reset to queued and requeued.",
        ))
        process_document_job.delay(job.id)
        stale_requeued += 1

    db.commit()
    return {
        "requeued": requeued,
        "stale_requeued": stale_requeued,
        "total_requeued": requeued + stale_requeued,
    }


def enqueue_recoverable_jobs_with_new_session() -> dict[str, int]:
    db = SessionLocal()
    try:
        return enqueue_recoverable_jobs(db)
    finally:
        db.close()
