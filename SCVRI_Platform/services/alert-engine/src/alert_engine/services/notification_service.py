"""Notification service — channel CRUD and multi-channel dispatch."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError
from scvri_shared.logging import get_logger
from alert_engine.schemas.notification import (
    ChannelType,
    DeliveryCause,
    NotificationChannelCreate,
    NotificationChannelResponse,
    NotificationChannelUpdate,
    NotificationLogResponse,
)

log = get_logger(__name__)

# Severity numeric weights for min_severity filtering
_SEVERITY_WEIGHT = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


# ── Channel CRUD ──────────────────────────────────────────────────────────────

async def create_channel(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: NotificationChannelCreate,
) -> NotificationChannelResponse:
    ch_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO alert.notification_channels
            (id, tenant_id, name, channel_type, config, min_severity,
             sources, is_active, rule_ids, sent_count, failed_count,
             created_by, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :name, :channel_type, :config::jsonb, :min_severity,
             :sources::jsonb, :is_active, :rule_ids::jsonb, 0, 0,
             :created_by, now(), now())
    """), {
        "id": str(ch_id),
        "tenant_id": str(tenant_id),
        "name": data.name,
        "channel_type": data.channel_type,
        "config": json.dumps(data.config.model_dump()),
        "min_severity": data.min_severity,
        "sources": json.dumps(data.sources),
        "is_active": data.is_active,
        "rule_ids": json.dumps([str(r) for r in data.rule_ids]),
        "created_by": str(user_id),
    })
    await db.commit()
    return await get_channel(db, tenant_id, ch_id)


async def get_channel(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    channel_id: uuid.UUID,
) -> NotificationChannelResponse:
    row = (await db.execute(text("""
        SELECT * FROM alert.notification_channels
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(channel_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"Notification channel {channel_id} not found")
    return _map_channel(row)


async def list_channels(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[NotificationChannelResponse]:
    rows = (await db.execute(text("""
        SELECT * FROM alert.notification_channels
        WHERE tenant_id = :tenant_id
        ORDER BY name
    """), {"tenant_id": str(tenant_id)})).mappings().all()
    return [_map_channel(r) for r in rows]


async def update_channel(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    channel_id: uuid.UUID,
    data: NotificationChannelUpdate,
) -> NotificationChannelResponse:
    await get_channel(db, tenant_id, channel_id)

    sets = ["updated_at = now()"]
    params: dict[str, Any] = {"id": str(channel_id), "tenant_id": str(tenant_id)}

    if data.name is not None:
        sets.append("name = :name"); params["name"] = data.name
    if data.config is not None:
        cfg = data.config if isinstance(data.config, dict) else data.config.model_dump()
        sets.append("config = :config::jsonb"); params["config"] = json.dumps(cfg)
    if data.min_severity is not None:
        sets.append("min_severity = :min_severity"); params["min_severity"] = data.min_severity
    if data.is_active is not None:
        sets.append("is_active = :is_active"); params["is_active"] = data.is_active

    await db.execute(text(f"""
        UPDATE alert.notification_channels
        SET {', '.join(sets)}
        WHERE id = :id AND tenant_id = :tenant_id
    """), params)
    await db.commit()
    return await get_channel(db, tenant_id, channel_id)


async def delete_channel(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    channel_id: uuid.UUID,
) -> None:
    await get_channel(db, tenant_id, channel_id)
    await db.execute(text("""
        UPDATE alert.notification_channels
        SET is_active = FALSE, updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(channel_id), "tenant_id": str(tenant_id)})
    await db.commit()


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def dispatch_notifications(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
    cause: DeliveryCause,
) -> int:
    """Dispatch notifications for an alert via all matching active channels."""
    # Fetch alert
    alert_row = (await db.execute(text("""
        SELECT * FROM alert.alerts WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(alert_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if alert_row is None:
        log.warning("dispatch.alert_not_found", alert_id=str(alert_id))
        return 0

    alert_severity = alert_row["severity"]
    alert_source = alert_row["source"]
    alert_rule_id = str(alert_row.get("rule_id") or "")

    # Fetch eligible channels
    channels = (await db.execute(text("""
        SELECT * FROM alert.notification_channels
        WHERE tenant_id = :tenant_id AND is_active = TRUE
    """), {"tenant_id": str(tenant_id)})).mappings().all()

    sent = 0
    for ch in channels:
        ch_config = ch.get("config") or {}
        if isinstance(ch_config, str):
            ch_config = json.loads(ch_config)

        # Severity filter
        min_sev = ch.get("min_severity", "medium")
        if _SEVERITY_WEIGHT.get(alert_severity, 0) < _SEVERITY_WEIGHT.get(min_sev, 0):
            continue

        # Source filter
        sources_raw = ch.get("sources") or "[]"
        sources = json.loads(sources_raw) if isinstance(sources_raw, str) else list(sources_raw)
        if sources and alert_source not in sources:
            continue

        # Rule filter
        rule_ids_raw = ch.get("rule_ids") or "[]"
        rule_ids = json.loads(rule_ids_raw) if isinstance(rule_ids_raw, str) else list(rule_ids_raw)
        if rule_ids and alert_rule_id not in rule_ids:
            continue

        channel_type: str = ch["channel_type"]
        log_id = uuid.uuid4()
        status = "pending"
        error_msg = None
        recipient_summary = ""

        try:
            if channel_type == "email":
                recipient_summary = await _send_email(alert_row, ch_config, cause)
            elif channel_type == "slack":
                recipient_summary = await _send_slack(alert_row, ch_config)
            elif channel_type == "webhook":
                recipient_summary = await _send_webhook(alert_row, ch_config)
            elif channel_type == "in_app":
                recipient_summary = await _send_in_app(db, alert_row, ch_config, tenant_id)
            else:
                status = "skipped"
                recipient_summary = f"unsupported channel type: {channel_type}"

            if status != "skipped":
                status = "sent"
            sent += 1

        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_msg = str(exc)
            log.warning(
                "dispatch.channel_failed",
                channel_id=str(ch["id"]),
                channel_type=channel_type,
                error=error_msg,
            )

        # Log the attempt
        await db.execute(text("""
            INSERT INTO alert.notification_logs
                (id, alert_id, channel_id, tenant_id, channel_type, status, cause,
                 recipient_summary, error_message, attempt_count, sent_at, created_at)
            VALUES
                (:id, :alert_id, :channel_id, :tenant_id, :ch_type, :status, :cause,
                 :recipient, :error, 1, :sent_at, now())
        """), {
            "id": str(log_id),
            "alert_id": str(alert_id),
            "channel_id": str(ch["id"]),
            "tenant_id": str(tenant_id),
            "ch_type": channel_type,
            "status": status,
            "cause": cause,
            "recipient": recipient_summary,
            "error": error_msg,
            "sent_at": datetime.now(timezone.utc) if status == "sent" else None,
        })

        # Update channel counters
        counter_col = "sent_count" if status == "sent" else "failed_count"
        await db.execute(text(f"""
            UPDATE alert.notification_channels
            SET {counter_col} = {counter_col} + 1,
                last_sent_at = CASE WHEN :sent THEN now() ELSE last_sent_at END,
                updated_at   = now()
            WHERE id = :ch_id
        """), {"sent": status == "sent", "ch_id": str(ch["id"])})

    # Update alert notification_count
    await db.execute(text("""
        UPDATE alert.alerts
        SET notification_count = notification_count + :sent, updated_at = now()
        WHERE id = :id
    """), {"sent": sent, "id": str(alert_id)})

    await db.commit()
    log.info("dispatch.complete", alert_id=str(alert_id), sent=sent, cause=cause)
    return sent


# ── Channel-specific senders ──────────────────────────────────────────────────

async def _send_email(alert_row: Any, config: dict, cause: str) -> str:
    """Send alert email via aiosmtplib (SMTP settings from env)."""
    import aiosmtplib  # noqa: PLC0415
    from email.message import EmailMessage  # noqa: PLC0415
    from scvri_shared.config import settings  # noqa: PLC0415

    recipients = config.get("recipients", [])
    cc = config.get("cc", [])
    prefix = config.get("subject_prefix", "[SCVRI Alert]")

    severity_emoji = {
        "critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "ℹ️"
    }.get(alert_row["severity"], "")

    subject = f"{prefix} {severity_emoji} {alert_row['severity'].upper()}: {alert_row['title']}"
    body = (
        f"Alert: {alert_row['title']}\n"
        f"Severity: {alert_row['severity'].upper()}\n"
        f"Status: {alert_row['status']}\n"
        f"Source: {alert_row['source']}\n\n"
        f"{alert_row['description']}\n\n"
        f"Cause: {cause}\n"
        f"Created: {alert_row['created_at']}\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = getattr(settings, "smtp_from_address", "alerts@scvri.io")
    msg["To"] = ", ".join(recipients)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(body)

    smtp_host = getattr(settings, "smtp_host", "localhost")
    smtp_port = getattr(settings, "smtp_port", 587)
    smtp_user = getattr(settings, "smtp_user", None)
    smtp_pass = getattr(settings, "smtp_password", None)

    await aiosmtplib.send(
        msg,
        hostname=smtp_host,
        port=smtp_port,
        username=smtp_user,
        password=smtp_pass,
        start_tls=smtp_port == 587,
    )
    return f"{len(recipients)} recipients"


async def _send_slack(alert_row: Any, config: dict) -> str:
    """Send Slack message via incoming webhook URL."""
    webhook_url = config.get("webhook_url", "")
    channel = config.get("channel")
    mentions = config.get("mention_user_ids", [])

    severity = alert_row["severity"]
    color_map = {
        "critical": "#FF0000",
        "high": "#FF7700",
        "medium": "#FFCC00",
        "low": "#00CC00",
        "info": "#0099FF",
    }

    mention_str = " ".join(f"<@{uid}>" for uid in mentions) if mentions and severity in ("critical", "high") else ""

    payload: dict[str, Any] = {
        "attachments": [{
            "color": color_map.get(severity, "#888888"),
            "title": f"[{severity.upper()}] {alert_row['title']}",
            "text": f"{mention_str}\n{alert_row['description']}",
            "fields": [
                {"title": "Source", "value": alert_row["source"], "short": True},
                {"title": "Status", "value": alert_row["status"], "short": True},
            ],
            "footer": "SCVRI Alert Engine",
            "ts": int(alert_row["created_at"].timestamp()),
        }]
    }
    if channel:
        payload["channel"] = channel

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()

    return f"Slack channel {channel or 'default'}"


async def _send_webhook(alert_row: Any, config: dict) -> str:
    """Send generic webhook POST."""
    import hashlib, hmac  # noqa: PLC0415

    url = config.get("url", "")
    method = config.get("method", "POST")
    headers = dict(config.get("headers", {}))
    timeout = config.get("timeout_seconds", 10)
    secret_header = config.get("secret_header")

    payload_dict = {
        "alert_id": str(alert_row["id"]),
        "title": alert_row["title"],
        "description": alert_row["description"],
        "severity": alert_row["severity"],
        "status": alert_row["status"],
        "source": alert_row["source"],
        "supplier_id": str(alert_row["supplier_id"]) if alert_row.get("supplier_id") else None,
        "created_at": alert_row["created_at"].isoformat(),
    }
    body = json.dumps(payload_dict)

    if secret_header:
        from scvri_shared.config import settings  # noqa: PLC0415
        webhook_secret = getattr(settings, "webhook_secret", "default-secret")
        sig = hmac.new(webhook_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers[secret_header] = f"sha256={sig}"

    headers.setdefault("Content-Type", "application/json")

    async with httpx.AsyncClient(timeout=timeout) as client:
        if method == "PUT":
            resp = await client.put(url, content=body, headers=headers)
        else:
            resp = await client.post(url, content=body, headers=headers)
        resp.raise_for_status()

    return f"POST {url}"


async def _send_in_app(
    db: AsyncSession,
    alert_row: Any,
    config: dict,
    tenant_id: uuid.UUID,
) -> str:
    """Persist in-app notification records for target users."""
    user_ids = config.get("user_ids", [])
    link_url = config.get("link_url")

    # If no user_ids specified, fetch all active users for tenant
    if not user_ids:
        rows = (await db.execute(text("""
            SELECT id FROM iam.users
            WHERE tenant_id = :tenant_id AND is_active = TRUE
        """), {"tenant_id": str(tenant_id)})).scalars().all()
        user_ids = [str(r) for r in rows]

    for uid in user_ids:
        await db.execute(text("""
            INSERT INTO alert.in_app_notifications
                (id, tenant_id, user_id, alert_id, title, description,
                 severity, link_url, is_read, created_at)
            VALUES
                (:id, :tenant_id, :user_id, :alert_id, :title, :desc,
                 :severity, :link_url, FALSE, now())
            ON CONFLICT DO NOTHING
        """), {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "user_id": str(uid),
            "alert_id": str(alert_row["id"]),
            "title": alert_row["title"],
            "desc": alert_row["description"],
            "severity": alert_row["severity"],
            "link_url": link_url,
        })

    return f"{len(user_ids)} in-app users"


# ── Notification log ──────────────────────────────────────────────────────────

async def list_notification_logs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    alert_id: uuid.UUID,
) -> list[NotificationLogResponse]:
    rows = (await db.execute(text("""
        SELECT * FROM alert.notification_logs
        WHERE alert_id = :alert_id AND tenant_id = :tenant_id
        ORDER BY created_at DESC
    """), {"alert_id": str(alert_id), "tenant_id": str(tenant_id)})).mappings().all()

    return [
        NotificationLogResponse(
            id=r["id"],
            alert_id=r["alert_id"],
            channel_id=r["channel_id"],
            channel_type=r["channel_type"],
            status=r["status"],
            cause=r["cause"],
            recipient_summary=r.get("recipient_summary", ""),
            error_message=r.get("error_message"),
            attempt_count=r.get("attempt_count", 1),
            sent_at=r.get("sent_at"),
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ── Digest ────────────────────────────────────────────────────────────────────

async def send_digest(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    channel_id: uuid.UUID,
    lookback_hours: int = 24,
    min_severity: str = "medium",
    include_resolved: bool = False,
) -> int:
    """Send a periodic digest of open alerts via the specified channel."""
    channel = await get_channel(db, tenant_id, channel_id)
    if not channel.is_active:
        return 0

    status_filter = "status IN ('open', 'acknowledged', 'escalated')"
    if include_resolved:
        status_filter = "status IN ('open', 'acknowledged', 'escalated', 'resolved')"

    alerts = (await db.execute(text(f"""
        SELECT * FROM alert.alerts
        WHERE tenant_id = :tenant_id
          AND {status_filter}
          AND created_at >= now() - (:hours * interval '1 hour')
          AND severity IN (
            SELECT unnest(ARRAY['critical','high','medium','low','info'])
            OFFSET (
                SELECT 4 - :sev_weight  -- slice from min_severity upward
            )
          )
        ORDER BY
            CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                          WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END,
            created_at DESC
    """), {
        "tenant_id": str(tenant_id),
        "hours": lookback_hours,
        "sev_weight": _SEVERITY_WEIGHT.get(min_severity, 2),
    })).mappings().all()

    if not alerts:
        return 0

    cfg = channel.config if isinstance(channel.config, dict) else {}
    digest_body = _build_digest_body(alerts, lookback_hours)

    if channel.channel_type == "email":
        from email.message import EmailMessage  # noqa: PLC0415
        import aiosmtplib  # noqa: PLC0415
        from scvri_shared.config import settings  # noqa: PLC0415

        recipients = cfg.get("recipients", [])
        prefix = cfg.get("subject_prefix", "[SCVRI Alert]")

        msg = EmailMessage()
        msg["Subject"] = f"{prefix} Alert Digest — last {lookback_hours}h ({len(alerts)} alerts)"
        msg["From"] = getattr(settings, "smtp_from_address", "alerts@scvri.io")
        msg["To"] = ", ".join(recipients)
        msg.set_content(digest_body)

        smtp_host = getattr(settings, "smtp_host", "localhost")
        smtp_port = getattr(settings, "smtp_port", 587)
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=getattr(settings, "smtp_user", None),
            password=getattr(settings, "smtp_password", None),
            start_tls=smtp_port == 587,
        )

    elif channel.channel_type == "slack":
        payload = {
            "text": f"*SCVRI Alert Digest — last {lookback_hours}h*\n```{digest_body}```"
        }
        if cfg.get("channel"):
            payload["channel"] = cfg["channel"]
        async with httpx.AsyncClient(timeout=10) as client:
            (await client.post(cfg.get("webhook_url", ""), json=payload)).raise_for_status()

    return len(alerts)


def _build_digest_body(alerts: list, lookback_hours: int) -> str:
    lines = [f"Alert Digest — past {lookback_hours} hours\n"]
    for a in alerts:
        lines.append(
            f"[{a['severity'].upper():8}] {a['status']:12} {str(a['created_at'])[:16]}  {a['title']}"
        )
    return "\n".join(lines)


# ── Mapper ────────────────────────────────────────────────────────────────────

def _map_channel(row: Any) -> NotificationChannelResponse:
    def _load(col: Any) -> list:
        if isinstance(col, str):
            return json.loads(col)
        return list(col) if col else []

    config = row.get("config") or {}
    if isinstance(config, str):
        config = json.loads(config)

    rule_ids_raw = _load(row.get("rule_ids"))
    rule_ids = []
    for r in rule_ids_raw:
        try:
            rule_ids.append(uuid.UUID(str(r)))
        except ValueError:
            pass

    return NotificationChannelResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        channel_type=row["channel_type"],
        config=config,
        min_severity=row.get("min_severity", "medium"),
        sources=_load(row.get("sources")),
        is_active=bool(row.get("is_active", True)),
        rule_ids=rule_ids,
        sent_count=row.get("sent_count", 0),
        failed_count=row.get("failed_count", 0),
        last_sent_at=row.get("last_sent_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
