"""Celery application — Beat schedules and task registration."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from scvri_shared.config import settings

celery_app = Celery(
    "alert_engine",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "alert_engine.workers.notification_worker",
    ],
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
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule={
        # Auto-escalate open alerts that have exceeded their rule's auto_escalate_minutes
        "auto_escalate_alerts": {
            "task": "alert_engine.workers.notification_worker.auto_escalate_alerts_task",
            "schedule": crontab(minute="*/15"),  # every 15 minutes
            "options": {"queue": "celery"},
        },
        # Daily alert digest — 08:00 UTC
        "send_daily_digests": {
            "task": "alert_engine.workers.notification_worker.send_digest_task",
            "schedule": crontab(hour=8, minute=0),
            "options": {"queue": "celery"},
        },
    },
)
