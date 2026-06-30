import os
from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "audit_ready_doc_pipeline",
    broker=REDIS_URL,
    backend=None,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_ignore_result=True,
    result_backend=None,
    task_track_started=False,
    broker_connection_retry_on_startup=True,
    task_default_queue="celery",
    timezone="UTC",
    beat_schedule={
        "run-job-recovery-every-minute": {
            "task": "run_job_recovery",
            "schedule": int(os.getenv("JOB_RECOVERY_INTERVAL_SECONDS", "60")),
        },
    },
)
