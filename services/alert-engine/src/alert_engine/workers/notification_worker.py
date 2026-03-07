"""Celery tasks — notification dispatch, auto-escalation, and digest."""
from __future__ import annotations

import asyncio
import uuid

from celery import Task
from celery.utils.log import get_task_logger

from alert_engine.workers.celery_app import celery_app
from scvri_shared.logging import get_logger

log = get_task_logger(__name__)


# ── Notification dispatch ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="alert_engine.workers.notification_worker.dispatch_alert_notifications_task",
    max_retries=3,
    default_retry_delay=30,
    queue="celery",
)
def dispatch_alert_notifications_task(
    self: Task,
    alert_id: str,
    tenant_id: str,
    cause: str = "alert_created",
) -> dict:
    """
    Celery task: dispatch notifications for a (alert_id, tenant_id, cause) tuple.

    Retries up to 3 times with 30-second back-off on transient failures.
    """
    async def _run() -> int:
        from alert_engine.services.notification_service import dispatch_notifications  # noqa: PLC0415
        from scvri_shared.database import get_tenant_session  # noqa: PLC0415

        tid = uuid.UUID(tenant_id)
        aid = uuid.UUID(alert_id)

        async with get_tenant_session(tid) as db:
            return await dispatch_notifications(db, tid, aid, cause)

    try:
        sent = asyncio.run(_run())
        log.info(f"dispatch.complete alert_id={alert_id} sent={sent} cause={cause}")
        return {"sent": sent, "alert_id": alert_id, "cause": cause}

    except Exception as exc:  # noqa: BLE001
        log.warning(f"dispatch.failed alert_id={alert_id} error={exc!r}; retrying")
        raise self.retry(exc=exc)


# ── Auto-escalation sweep ─────────────────────────────────────────────────────

@celery_app.task(
    name="alert_engine.workers.notification_worker.auto_escalate_alerts_task",
    queue="celery",
)
def auto_escalate_alerts_task() -> dict:
    """
    Beat task — sweep all tenants and escalate open alerts that have
    exceeded their rule's auto_escalate_minutes threshold.
    """
    async def _run() -> int:
        from sqlalchemy import text  # noqa: PLC0415
        from scvri_shared.database import get_engine  # noqa: PLC0415
        from alert_engine.services.alert_service import auto_escalate_stale_alerts  # noqa: PLC0415

        engine = get_engine()
        total = 0

        async with engine.begin() as conn:
            tenant_rows = (await conn.execute(text(
                "SELECT id FROM iam.tenants WHERE is_active = TRUE"
            ))).scalars().all()

        for tenant_id_raw in tenant_rows:
            tid = uuid.UUID(str(tenant_id_raw))
            from scvri_shared.database import get_tenant_session  # noqa: PLC0415
            async with get_tenant_session(tid) as db:
                count = await auto_escalate_stale_alerts(db, tid)
                total += count

        return total

    escalated = asyncio.run(_run())
    log.info(f"auto_escalate.complete escalated={escalated}")
    return {"escalated": escalated}


# ── Digest emails ─────────────────────────────────────────────────────────────

@celery_app.task(
    name="alert_engine.workers.notification_worker.send_digest_task",
    queue="celery",
)
def send_digest_task() -> dict:
    """
    Beat task (daily 08:00 UTC) — send alert digest to all active digest channels
    across all tenants.
    """
    async def _run() -> int:
        from sqlalchemy import text  # noqa: PLC0415
        from scvri_shared.database import get_engine, get_tenant_session  # noqa: PLC0415
        from alert_engine.services.notification_service import send_digest  # noqa: PLC0415

        engine = get_engine()
        total_digests = 0

        async with engine.begin() as conn:
            tenant_rows = (await conn.execute(text(
                "SELECT id FROM iam.tenants WHERE is_active = TRUE"
            ))).scalars().all()

        for tenant_id_raw in tenant_rows:
            tid = uuid.UUID(str(tenant_id_raw))
            async with get_tenant_session(tid) as db:
                # Find all active email/slack channels that are flagged as digest channels
                from sqlalchemy import text as _t  # noqa: PLC0415
                channels = (await db.execute(_t("""
                    SELECT id FROM alert.notification_channels
                    WHERE tenant_id = :tid AND is_active = TRUE
                      AND channel_type IN ('email', 'slack')
                      AND config->>'digest_enabled' = 'true'
                """), {"tid": str(tid)})).scalars().all()

                for ch_id_raw in channels:
                    try:
                        count = await send_digest(
                            db,
                            tenant_id=tid,
                            channel_id=uuid.UUID(str(ch_id_raw)),
                        )
                        total_digests += count
                    except Exception as exc:  # noqa: BLE001
                        log.warning(f"digest.failed channel_id={ch_id_raw} error={exc!r}")

        return total_digests

    sent = asyncio.run(_run())
    log.info(f"send_digest.complete total_alerts_in_digests={sent}")
    return {"total_alerts_in_digests": sent}
