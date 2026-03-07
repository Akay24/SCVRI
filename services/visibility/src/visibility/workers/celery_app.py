"""Celery application for the Visibility service."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from scvri_shared.config import settings

app = Celery(
    "visibility",
    broker=str(settings.redis_url),
    backend=str(settings.redis_url),
    include=[
        "visibility.workers.erp_sync_worker",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="visibility",
    task_queues={
        "visibility": {"exchange": "visibility", "routing_key": "visibility"},
    },
)

# ── Beat schedules ────────────────────────────────────────────────────────────

app.conf.beat_schedule = {
    # Sync PO statuses from ERP every 30 minutes
    "erp_sync_pos_task": {
        "task": "visibility.workers.erp_sync_worker.erp_sync_pos_task",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "visibility"},
    },
    # Daily reconciliation of shipment statuses from carrier APIs at 03:00 UTC
    "reconcile_shipments_task": {
        "task": "visibility.workers.erp_sync_worker.reconcile_shipments_task",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "visibility"},
    },
}
