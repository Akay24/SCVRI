"""Alert engine Celery worker entrypoint."""
from alert_engine.workers.celery_app import celery_app

__all__ = ["celery_app"]
