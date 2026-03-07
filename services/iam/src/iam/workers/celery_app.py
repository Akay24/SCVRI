"""IAM Celery application — scheduled token maintenance tasks."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from scvri_shared.config import settings

celery_app = Celery(
    "iam",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["iam.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        # Purge expired password reset tokens from DB (housekeeping)
        "purge_expired_sessions": {
            "task": "iam.workers.tasks.purge_expired_sessions_task",
            "schedule": crontab(hour=3, minute=0),  # daily at 03:00 UTC
            "options": {"queue": "celery"},
        },
    },
)
