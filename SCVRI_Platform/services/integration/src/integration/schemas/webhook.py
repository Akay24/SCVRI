"""Webhook ingestion schemas."""
from __future__ import annotations

import enum
import hashlib
import hmac
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class WebhookSource(str, enum.Enum):
    SAP = "sap"
    ORACLE = "oracle"
    SUPPLIER_PORTAL = "supplier_portal"
    CUSTOM = "custom"


class WebhookEventType(str, enum.Enum):
    SUPPLIER_UPDATED = "supplier.updated"
    SUPPLIER_CREATED = "supplier.created"
    PURCHASE_ORDER_CREATED = "purchase_order.created"
    PURCHASE_ORDER_UPDATED = "purchase_order.updated"
    INVOICE_RECEIVED = "invoice.received"
    DELIVERY_CONFIRMED = "delivery.confirmed"
    RISK_ALERT = "risk.alert"
    UNKNOWN = "unknown"


class InboundWebhookPayload(BaseModel):
    """Raw inbound webhook body; normalised before Kafka publication."""

    source: WebhookSource
    event_type: str
    event_id: str = Field(..., description="Idempotency key from source")
    tenant_id: UUID
    occurred_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class WebhookRegistration(BaseModel):
    """A tenant's registered inbound webhook endpoint configuration."""

    id: UUID | None = None
    tenant_id: UUID
    source: WebhookSource
    signing_secret: str = Field(..., description="HMAC-SHA256 signing secret")
    description: str = ""
    active: bool = True
    created_at: datetime | None = None


class WebhookDeliveryLog(BaseModel):
    """Audit record of every received webhook."""

    id: UUID | None = None
    registration_id: UUID
    event_id: str
    event_type: str
    received_at: datetime
    signature_valid: bool
    processed: bool
    kafka_offset: int | None = None
    error: str | None = None


class NormalisedEvent(BaseModel):
    """Platform-canonical event shape published to Kafka."""

    event_id: str
    event_type: WebhookEventType
    source: WebhookSource
    tenant_id: UUID
    occurred_at: datetime
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


def verify_webhook_signature(
    body: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Validate HMAC-SHA256 signature sent in X-Webhook-Signature header.

    Header format: ``sha256=<hex_digest>``
    """
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
