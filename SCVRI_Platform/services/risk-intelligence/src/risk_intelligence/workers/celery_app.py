"""Celery application factory for the Risk Intelligence service.

Workers:
  - risk_score_worker: compute_risk_score_task — per-supplier scoring
  - kri_evaluation_worker: evaluate_all_kris_task — periodic KRI sweep

Beat schedules:
  - Full risk score recompute for all active suppliers: 02:00 UTC daily
  - KRI evaluation sweep: every 6 hours
  - Model performance report: 06:00 UTC Monday

Start worker:
  celery -A risk_intelligence.workers.celery_app worker -l info -Q risk_intelligence

Start beat:
  celery -A risk_intelligence.workers.celery_app beat -l info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from scvri_shared.config import settings

app = Celery(
    "risk_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "risk_intelligence.workers.risk_score_worker",
        "risk_intelligence.workers.kri_evaluation_worker",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 7200},  # 2h — large batch scoring
    result_expires=3600,
    task_routes={
        "risk_intelligence.workers.*": {"queue": "risk_intelligence"},
    },
    task_max_retries=3,
    task_default_retry_delay=120,
    # Concurrency: ML inference is CPU-bound — use prefork with limited workers
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
)

app.conf.beat_schedule = {
    "nightly-risk-rescore": {
        "task": "risk_intelligence.workers.risk_score_worker.rescore_all_suppliers_task",
        "schedule": crontab(minute=0, hour=2),   # 02:00 UTC daily
        "options": {"queue": "risk_intelligence"},
    },
    "kri-evaluation-sweep": {
        "task": "risk_intelligence.workers.kri_evaluation_worker.evaluate_all_kris_task",
        "schedule": crontab(minute=0, hour="*/6"),  # every 6 hours
        "options": {"queue": "risk_intelligence"},
    },
}

if __name__ == "__main__":
    app.start()
