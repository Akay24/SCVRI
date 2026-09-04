"""Notifications router — channel CRUD, logs, and test-send."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession


from alert_engine.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    get_tenant_db,
    require_admin,
    require_write_access,
)
from alert_engine.schemas.notification import (
    NotificationChannelCreate,
    NotificationChannelResponse,
    NotificationChannelUpdate,
    NotificationLogResponse,
)
from alert_engine.services import notification_service

router = APIRouter(tags=["notifications"])

DbDep = TenantDB
WriteDep = Annotated[None, Depends(require_write_access)]
AdminDep = Annotated[None, Depends(require_admin)]


# ── Channels ───────────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[NotificationChannelResponse])
async def list_channels(
    db: DbDep,
    tenant_id: TenantID,
) -> list[NotificationChannelResponse]:
    return await notification_service.list_channels(db, tenant_id)


@router.post(
    "/channels",
    response_model=NotificationChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    data: NotificationChannelCreate,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: AdminDep,
) -> NotificationChannelResponse:
    """Create a notification channel (admin only)."""
    return await notification_service.create_channel(
        db, tenant_id, user_id, data
    )


@router.get("/channels/{channel_id}", response_model=NotificationChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    db: DbDep,
    tenant_id: TenantID,
) -> NotificationChannelResponse:
    return await notification_service.get_channel(db, tenant_id, channel_id)


@router.patch("/channels/{channel_id}", response_model=NotificationChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    data: NotificationChannelUpdate,
    db: DbDep,
    tenant_id: TenantID,
    _: AdminDep,
) -> NotificationChannelResponse:
    """Update channel config (admin only)."""
    return await notification_service.update_channel(
        db, tenant_id, channel_id, data
    )


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_channel(
    channel_id: uuid.UUID,
    db: DbDep,
    tenant_id: TenantID,
    _: AdminDep,
) -> Response:
    """Deactivate a channel (admin only)."""
    await notification_service.delete_channel(db, tenant_id, channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: uuid.UUID,
    db: DbDep,
    tenant_id: TenantID,
    _: AdminDep,
) -> dict[str, str]:
    """Send a test notification through this channel."""
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

    channel = await notification_service.get_channel(db, tenant_id, channel_id)
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
    tenant_id: TenantID,
) -> list[NotificationLogResponse]:
    """Delivery log for a specific alert."""
    return await notification_service.list_notification_logs(
        db, tenant_id, alert_id
    )
