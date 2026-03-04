"""Notifications router — channel CRUD, logs, and test-send."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from alert_engine.dependencies import get_tenant_db, require_admin, require_write_access
from alert_engine.schemas.notification import (
    NotificationChannelCreate,
    NotificationChannelResponse,
    NotificationChannelUpdate,
    NotificationLogResponse,
)
from alert_engine.services import notification_service
from scvri_shared.auth import TokenClaims

router = APIRouter(tags=["notifications"])

DbDep = Annotated[AsyncSession, Depends(get_tenant_db)]
WriteDep = Annotated[TokenClaims, Depends(require_write_access)]
AdminDep = Annotated[TokenClaims, Depends(require_admin)]


# ── Channels ───────────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[NotificationChannelResponse])
async def list_channels(
    db: DbDep,
    claims: Annotated[TokenClaims, Depends()],
) -> list[NotificationChannelResponse]:
    return await notification_service.list_channels(db, claims.tenant_id)


@router.post(
    "/channels",
    response_model=NotificationChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    data: NotificationChannelCreate,
    db: DbDep,
    claims: AdminDep,
) -> NotificationChannelResponse:
    """Create a notification channel (admin only)."""
    return await notification_service.create_channel(
        db, claims.tenant_id, claims.user_id, data
    )


@router.get("/channels/{channel_id}", response_model=NotificationChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    db: DbDep,
    claims: Annotated[TokenClaims, Depends()],
) -> NotificationChannelResponse:
    return await notification_service.get_channel(db, claims.tenant_id, channel_id)


@router.patch("/channels/{channel_id}", response_model=NotificationChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    data: NotificationChannelUpdate,
    db: DbDep,
    claims: AdminDep,
) -> NotificationChannelResponse:
    """Update channel config (admin only)."""
    return await notification_service.update_channel(
        db, claims.tenant_id, channel_id, data
    )


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    db: DbDep,
    claims: AdminDep,
) -> None:
    """Deactivate a channel (admin only)."""
    await notification_service.delete_channel(db, claims.tenant_id, channel_id)


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: uuid.UUID,
    db: DbDep,
    claims: AdminDep,
) -> dict[str, str]:
    """Send a test notification through this channel."""
    from sqlalchemy import text  # noqa: PLC0415

    # Build a synthetic alert dict for testing
    fake_alert: dict = {
        "id": str(uuid.uuid4()),
        "title": "Test Alert — channel verification",
        "description": "This is a test notification from SCVRI Alert Engine.",
        "severity": "info",
        "status": "open",
        "source": "system",
        "supplier_id": None,
        "created_at": __import__("datetime").datetime.utcnow(),
    }

    channel = await notification_service.get_channel(db, claims.tenant_id, channel_id)
    cfg = channel.config if isinstance(channel.config, dict) else {}

    try:
        if channel.channel_type == "email":
            result = await notification_service._send_email(fake_alert, cfg, "test")
        elif channel.channel_type == "slack":
            result = await notification_service._send_slack(fake_alert, cfg)
        elif channel.channel_type == "webhook":
            result = await notification_service._send_webhook(fake_alert, cfg)
        else:
            result = f"test not supported for {channel.channel_type}"
        return {"status": "ok", "details": result}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "details": str(exc)}


# ── Notification logs ─────────────────────────────────────────────────────────

@router.get(
    "/alerts/{alert_id}/notifications",
    response_model=list[NotificationLogResponse],
)
async def get_alert_notifications(
    alert_id: uuid.UUID,
    db: DbDep,
    claims: Annotated[TokenClaims, Depends()],
) -> list[NotificationLogResponse]:
    """Delivery log for a specific alert."""
    return await notification_service.list_notification_logs(
        db, claims.tenant_id, alert_id
    )
