"""Outbound push notification schemas."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class OutboundEventType(str, enum.Enum):
    RISK_SCORE_UPDATED = "risk_score.updated"
    ALERT_TRIGGERED = "alert.triggered"
    SUPPLIER_STATUS_CHANGED = "supplier.status_changed"
    SCORECARD_GENERATED = "scorecard.generated"


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class OutboundEndpoint(BaseModel):
    """External system endpoint registered to receive SCVRI push events."""

    id: UUID | None = None
    tenant_id: UUID
    name: str
    url: str
    secret: str = Field(..., description="HMAC-SHA256 signing secret for outbound payloads")
    event_types: list[OutboundEventType] = Field(default_factory=list)
    active: bool = True
    created_at: datetime | None = None
    timeout_seconds: int = 10
    retry_max: int = 3


class OutboundPushPayload(BaseModel):
    """Canonical shape of every outbound push notification."""

    event_id: str
    event_type: OutboundEventType
    tenant_id: UUID
    occurred_at: datetime
    entity_type: str
    entity_id: str
    data: dict[str, Any] = Field(default_factory=dict)


class OutboundDeliveryAttempt(BaseModel):
    id: UUID | None = None
    endpoint_id: UUID
    event_id: str
    event_type: OutboundEventType
    attempt_number: int = 1
    scheduled_at: datetime
    delivered_at: datetime | None = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    response_code: int | None = None
    response_body: str | None = None
    error: str | None = None


class OutboundPushRequest(BaseModel):
    """Manual trigger for pushing an event to all matching endpoints."""

    tenant_id: UUID
    event_type: OutboundEventType
    entity_type: str
    entity_id: str
    data: dict[str, Any] = Field(default_factory=dict)


class OutboundPushResult(BaseModel):
    event_id: str
    endpoints_targeted: int
    delivered: int
    failed: int
