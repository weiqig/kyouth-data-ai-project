from __future__ import annotations

from app.recovery import enqueue_recoverable_jobs_with_new_session


if __name__ == "__main__":
    result = enqueue_recoverable_jobs_with_new_session()
    print(result)
