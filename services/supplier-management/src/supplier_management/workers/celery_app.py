"""Celery application factory for the Supplier Management service.

Workers:
  - scorecard_worker: compute_supplier_scorecard — triggered on demand
  - cert_expiry_worker: check_cert_expiry — Celery Beat, every 4 hours

Start worker:
  celery -A supplier_management.workers.celery_app worker -l info -Q supplier_management

Start Beat scheduler:
  celery -A supplier_management.workers.celery_app beat -l info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from scvri_shared.config import settings

app = Celery(
    "supplier_management",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "supplier_management.workers.scorecard_worker",
        "supplier_management.workers.cert_expiry_worker",
    ],
)

# ---------------------------------------------------------------------------
# Celery config
# ---------------------------------------------------------------------------
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Acknowledgment after task completes (not on pickup) — safe for retries
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Visibility timeout — longer than the slowest expected task (cert scan over all tenants)
    broker_transport_options={"visibility_timeout": 3600},
    # Result expiry — 1 hour
    result_expires=3600,
    # Queue routing
    task_routes={
        "supplier_management.workers.scorecard_worker.*": {"queue": "supplier_management"},
        "supplier_management.workers.cert_expiry_worker.*": {"queue": "supplier_management"},
    },
    # Retry defaults
    task_max_retries=3,
    task_default_retry_delay=60,  # seconds
)

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------
app.conf.beat_schedule = {
    "check-cert-expiry-every-4h": {
        "task": "supplier_management.workers.cert_expiry_worker.check_cert_expiry",
        "schedule": crontab(minute=0, hour="*/4"),
        "options": {"queue": "supplier_management"},
    },
}

if __name__ == "__main__":
    app.start()
