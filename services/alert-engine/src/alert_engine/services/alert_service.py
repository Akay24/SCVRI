"""Alert service — create, query, and lifecycle management."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError, BusinessRuleError
from scvri_shared.kafka import get_producer
from scvri_shared.logging import get_logger
from alert_engine.schemas.alert import (
    ALERT_STATUS_ORDER,
    AlertAcknowledgeRequest,
    AlertCreate,
    AlertEscalateRequest,
    AlertResolveRequest,
    AlertResponse,
    AlertSummaryResponse,
    AlertSuppressRequest,
    AlertUpdate,
)
from alert_engine.workers.notification_worker import dispatch_alert_notifications_task

log = get_logger(__name__)


# ── Create ────────────────────────────────────────────────────────────────────

async def create_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: AlertCreate,
    *,
    skip_notification: bool = False,
) -> AlertResponse:
    alert_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO alert.alerts
            (id, tenant_id, title, description, severity, status, source,
             source_event_type, source_event_id, supplier_id, rule_id, payload,
             notification_count, created_by, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :title, :description, :severity, 'open', :source,
             :source_event_type, :source_event_id, :supplier_id, :rule_id, :payload::jsonb,
             0, :created_by, now(), now())
    """), {
        "id": str(alert_id),
        "tenant_id": str(tenant_id),
        "title": data.title,
        "description": data.description,
        "severity": data.severity,
        "source": data.source,
        "source_event_type": data.source_event_type,
        "source_event_id": data.source_event_id,
        "supplier_id": str(data.supplier_id) if data.supplier_id else None,
        "rule_id": str(data.rule_id) if data.rule_id else None,
        "payload": __import__("json").dumps(data.payload),
        "created_by": str(user_id),
    })

    await db.commit()

    alert = await get_alert(db, tenant_id, alert_id)
    log.info("alert.created", alert_id=str(alert_id), severity=data.severity, source=data.source)

    if not skip_notification:
        # Enqueue notification dispatch asynchronously
        dispatch_alert_notifications_task.delay(
            str(alert_id), str(tenant_id), "alert_created"
        )

    return alert


# ── Query ─────────────────────────────────────────────────────────────────────

async def get_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
) -> AlertResponse:
    row = (await db.execute(text("""
        SELECT * FROM alert.alerts
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(alert_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"Alert {alert_id} not found")
    return _map_alert(row)


async def list_alerts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    status: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    supplier_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AlertResponse]:
    filters = "tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": limit, "offset": offset}

    if status:
        filters += " AND status = :status"
        params["status"] = status
    if severity:
        filters += " AND severity = :severity"
        params["severity"] = severity
    if source:
        filters += " AND source = :source"
        params["source"] = source
    if supplier_id:
        filters += " AND supplier_id = :supplier_id"
        params["supplier_id"] = str(supplier_id)

    rows = (await db.execute(text(f"""
        SELECT * FROM alert.alerts
        WHERE {filters}
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
                ELSE 5
            END,
            created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    return [_map_alert(r) for r in rows]


async def get_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> AlertSummaryResponse:
    row = (await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'open') AS total_open,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'critical') AS critical,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'high') AS high,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'medium') AS medium,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'low') AS low,
            COUNT(*) FILTER (WHERE status = 'open' AND severity = 'info') AS info,
            COUNT(*) FILTER (WHERE status = 'acknowledged') AS acknowledged,
            COUNT(*) FILTER (WHERE status = 'escalated') AS escalated,
            COUNT(*) FILTER (
                WHERE status = 'resolved'
                  AND resolved_at >= now() - interval '24 hours'
            ) AS resolved_last_24h
        FROM alert.alerts
        WHERE tenant_id = :tenant_id
    """), {"tenant_id": str(tenant_id)})).mappings().one()

    return AlertSummaryResponse(
        total_open=row["total_open"] or 0,
        critical=row["critical"] or 0,
        high=row["high"] or 0,
        medium=row["medium"] or 0,
        low=row["low"] or 0,
        info=row["info"] or 0,
        acknowledged=row["acknowledged"] or 0,
        escalated=row["escalated"] or 0,
        resolved_last_24h=row["resolved_last_24h"] or 0,
    )


# ── Lifecycle transitions ─────────────────────────────────────────────────────

async def acknowledge_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    data: AlertAcknowledgeRequest,
) -> AlertResponse:
    alert = await _fetch_and_validate(db, tenant_id, alert_id, allowed_statuses={"open", "escalated"})

    await db.execute(text("""
        UPDATE alert.alerts
        SET status          = 'acknowledged',
            acknowledged_at = now(),
            assignee_id     = COALESCE(:assignee, assignee_id),
            updated_at      = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "assignee": str(data.assignee_id) if data.assignee_id else None,
        "id": str(alert_id),
        "tenant_id": str(tenant_id),
    })
    await db.commit()

    updated = await get_alert(db, tenant_id, alert_id)
    log.info("alert.acknowledged", alert_id=str(alert_id), by=str(user_id))
    return updated


async def resolve_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    data: AlertResolveRequest,
) -> AlertResponse:
    await _fetch_and_validate(
        db, tenant_id, alert_id,
        allowed_statuses={"open", "acknowledged", "escalated"},
    )

    await db.execute(text("""
        UPDATE alert.alerts
        SET status           = 'resolved',
            resolved_at      = now(),
            resolution_notes = :notes,
            updated_at       = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "notes": data.resolution_notes or data.resolution_note,
        "id": str(alert_id),
        "tenant_id": str(tenant_id),
    })
    await db.commit()

    updated = await get_alert(db, tenant_id, alert_id)
    log.info("alert.resolved", alert_id=str(alert_id), by=str(user_id))

    # Notify resolution
    dispatch_alert_notifications_task.delay(str(alert_id), str(tenant_id), "alert_resolved")

    # Kafka
    async with get_producer() as producer:
        await producer.send(
            topic="alert.notifications",
            event_type="alert.resolved",
            payload={"alert_id": str(alert_id), "resolved_by": str(user_id)},
            tenant_id=str(tenant_id),
        )

    return updated


async def suppress_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    data: AlertSuppressRequest,
) -> AlertResponse:
    await _fetch_and_validate(
        db, tenant_id, alert_id,
        allowed_statuses={"open", "acknowledged", "escalated"},
    )

    await db.execute(text("""
        UPDATE alert.alerts
        SET status           = 'suppressed',
            suppressed_until = :until,
            resolution_notes = COALESCE(:reason, resolution_notes),
            updated_at       = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "until": data.suppress_until,
        "reason": data.reason,
        "id": str(alert_id),
        "tenant_id": str(tenant_id),
    })
    await db.commit()
    log.info("alert.suppressed", alert_id=str(alert_id), until=str(data.suppress_until))
    return await get_alert(db, tenant_id, alert_id)


async def escalate_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
    data: AlertEscalateRequest,
) -> AlertResponse:
    await _fetch_and_validate(
        db, tenant_id, alert_id,
        allowed_statuses={"open", "acknowledged"},
    )

    await db.execute(text("""
        UPDATE alert.alerts
        SET status       = 'escalated',
            escalated_at = now(),
            assignee_id  = :assignee,
            updated_at   = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "assignee": str(data.escalate_to_user_id),
        "id": str(alert_id),
        "tenant_id": str(tenant_id),
    })
    await db.commit()

    updated = await get_alert(db, tenant_id, alert_id)
    log.info("alert.escalated", alert_id=str(alert_id), to=str(data.escalate_to_user_id))

    dispatch_alert_notifications_task.delay(str(alert_id), str(tenant_id), "alert_escalated")

    return updated


# ── Auto-escalation sweep ─────────────────────────────────────────────────────

async def auto_escalate_stale_alerts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> int:
    """Escalate open alerts whose rules specify auto_escalate_minutes and have exceeded the window."""
    result = await db.execute(text("""
        UPDATE alert.alerts a
        SET status       = 'escalated',
            escalated_at  = now(),
            updated_at    = now()
        FROM alert.alert_rules r
        WHERE a.rule_id = r.id
          AND a.tenant_id = :tenant_id
          AND a.status = 'open'
          AND r.auto_escalate_minutes IS NOT NULL
          AND a.created_at < now() - (r.auto_escalate_minutes * interval '1 minute')
        RETURNING a.id
    """), {"tenant_id": str(tenant_id)})
    escalated_ids = result.scalars().all()
    await db.commit()

    for aid in escalated_ids:
        dispatch_alert_notifications_task.delay(str(aid), str(tenant_id), "alert_escalated")

    if escalated_ids:
        log.info("alert.auto_escalated", count=len(escalated_ids))
    return len(escalated_ids)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_and_validate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
    allowed_statuses: set[str],
) -> AlertResponse:
    alert = await get_alert(db, tenant_id, alert_id)
    if alert.status not in allowed_statuses:
        raise BusinessRuleError(
            f"Cannot perform this action on alert with status '{alert.status}'"
        )
    return alert


def _map_alert(row: Any) -> AlertResponse:
    import json  # noqa: PLC0415
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)

    return AlertResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        title=row["title"],
        description=row["description"],
        severity=row["severity"],
        status=row["status"],
        source=row["source"],
        source_event_type=row.get("source_event_type"),
        source_event_id=row.get("source_event_id"),
        supplier_id=row.get("supplier_id"),
        rule_id=row.get("rule_id"),
        payload=payload,
        assignee_id=row.get("assignee_id"),
        acknowledged_at=row.get("acknowledged_at"),
        resolved_at=row.get("resolved_at"),
        suppressed_until=row.get("suppressed_until"),
        resolution_notes=row.get("resolution_notes"),
        escalated_at=row.get("escalated_at"),
        notification_count=row.get("notification_count", 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
