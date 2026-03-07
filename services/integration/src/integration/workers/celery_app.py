"""Celery application for Integration service background tasks."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from scvri_shared.config import get_settings

settings = get_settings()

app = Celery(
    "integration",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["integration.workers.tasks"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_default_retry_delay=60,
    task_max_retries=3,
    result_expires=86400,
    beat_schedule={
        # ERP full sync — each tenant, all systems, all entity types
        # Runs every 6 hours; individual syncs are triggered per-tenant via tasks.
        "erp-scheduled-sync": {
            "task": "integration.workers.tasks.scheduled_erp_sync_all_tenants",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        # Retry failed outbound deliveries
        "retry-failed-deliveries": {
            "task": "integration.workers.tasks.retry_failed_outbound_deliveries",
            "schedule": crontab(minute="*/15"),
        },
        # Purge delivery log rows older than 90 days
        "purge-old-delivery-logs": {
            "task": "integration.workers.tasks.purge_old_delivery_logs",
            "schedule": crontab(minute=30, hour=3),
        },
    },
)
