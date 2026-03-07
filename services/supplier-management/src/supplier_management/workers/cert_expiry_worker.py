"""Celery Beat task — certificate expiry monitor.

Runs every 4 hours (configured in celery_app.py Beat schedule).

For each tenant:
  - Find all active certifications expiring in the next 30, 7, or 0 days
  - Publish an `alert.triggered` Kafka event for each expiring cert

Kafka event type:
  - certification.expiring.30d
  - certification.expiring.7d
  - certification.expired
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from celery import shared_task
from sqlalchemy import select, text

from scvri_shared.config import settings
from scvri_shared.logging import get_logger
from scvri_shared.models.supplier import Certification
from supplier_management.workers.celery_app import app

log = get_logger(__name__)

_ALERT_WINDOWS: list[tuple[int, str]] = [
    (0,  "certification.expired"),
    (7,  "certification.expiring.7d"),
    (30, "certification.expiring.30d"),
]


@app.task(
    name="supplier_management.workers.cert_expiry_worker.check_cert_expiry",
    max_retries=2,
    default_retry_delay=300,
)
def check_cert_expiry() -> dict:
    """Scan all tenants for expiring/expired certifications and emit alert events."""
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415
    from scvri_shared.models.tenant import Tenant  # noqa: PLC0415

    log.info("cert_expiry.check.start")

    engine = create_engine(str(settings.database_url_sync), pool_pre_ping=True)
    total_alerts = 0

    with Session(engine) as sess:
        # Get all active tenants
        tenants = sess.execute(
            select(Tenant.id).where(Tenant.status == "active")
        ).scalars().all()

        today = date.today()

        for tenant_id in tenants:
            sess.execute(text(f"SET LOCAL scvri.tenant_id = '{tenant_id}'"))

            for days_ahead, event_type in _ALERT_WINDOWS:
                target_date = today + timedelta(days=days_ahead)

                if days_ahead == 0:
                    # Already expired
                    certs = sess.execute(
                        select(Certification).where(
                            Certification.expiry_date <= today,
                            Certification.status == "active",
                        )
                    ).scalars().all()
                else:
                    # Expiring soon — exact day match avoids duplicate alerts
                    certs = sess.execute(
                        select(Certification).where(
                            Certification.expiry_date == target_date,
                            Certification.status == "active",
                        )
                    ).scalars().all()

                for cert in certs:
                    _emit_cert_alert(tenant_id, cert, event_type)
                    total_alerts += 1

                    if days_ahead == 0:
                        # Mark as expired in DB
                        cert.status = "expired"

        sess.commit()

    log.info("cert_expiry.check.done", total_alerts=total_alerts)
    return {"total_alerts": total_alerts}


def _emit_cert_alert(tenant_id: uuid.UUID, cert: Certification, event_type: str) -> None:
    """Publish a Kafka event to the alert.triggered topic (synchronous wrapper)."""
    import asyncio  # noqa: PLC0415

    async def _publish() -> None:
        from scvri_shared.kafka import get_producer  # noqa: PLC0415
        async with get_producer() as producer:
            await producer.publish(
                topic="alert.triggered",
                key=str(cert.supplier_id),
                value={
                    "tenant_id": str(tenant_id),
                    "supplier_id": str(cert.supplier_id),
                    "certification_id": str(cert.id),
                    "certification_type": cert.certification_type,
                    "expiry_date": cert.expiry_date.isoformat(),
                    "event_type": event_type,
                },
                event_type=event_type,
            )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures  # noqa: PLC0415
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _publish())
                future.result(timeout=10)
        else:
            loop.run_until_complete(_publish())
    except Exception as exc:  # noqa: BLE001
        log.error(
            "cert_expiry.kafka.failed",
            cert_id=str(cert.id),
            event_type=event_type,
            error=str(exc),
        )
