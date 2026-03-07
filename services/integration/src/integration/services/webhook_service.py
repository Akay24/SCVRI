"""Webhook ingestion service — validate, normalise, and publish inbound webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from integration.core.kafka_producer import publish_webhook_event
from integration.core.rate_limiter import (
    RateLimitExceeded,
    SlidingWindowRateLimiter,
    WEBHOOK_RATE_LIMIT,
    WEBHOOK_RATE_WINDOW,
)
from integration.schemas.webhook import (
    InboundWebhookPayload,
    NormalisedEvent,
    WebhookDeliveryLog,
    WebhookEventType,
    WebhookRegistration,
    WebhookSource,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)


class WebhookSignatureError(Exception):
    """Raised when an inbound webhook HMAC signature is invalid."""


class WebhookNotFoundError(Exception):
    """Raised when no active webhook registration is found."""


# ── Registration CRUD ──────────────────────────────────────────────────────────

async def create_webhook_registration(
    db: AsyncSession,
    registration: WebhookRegistration,
) -> WebhookRegistration:
    result = await db.execute(
        text(
            """
            INSERT INTO integration.webhook_registrations
                (tenant_id, source, signing_secret, description, active)
            VALUES
                (:tenant_id, :source, :signing_secret, :description, :active)
            RETURNING id, tenant_id, source, signing_secret, description, active, created_at
            """
        ),
        {
            "tenant_id": str(registration.tenant_id),
            "source": registration.source.value,
            "signing_secret": registration.signing_secret,
            "description": registration.description,
            "active": registration.active,
        },
    )
    await db.commit()
    row = dict(result.mappings().one())
    return WebhookRegistration(**row)


async def get_registration(
    db: AsyncSession,
    registration_id: UUID,
    tenant_id: UUID,
) -> WebhookRegistration | None:
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, source, signing_secret, description, active, created_at
            FROM integration.webhook_registrations
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": str(registration_id), "tenant_id": str(tenant_id)},
    )
    row = result.mappings().one_or_none()
    return WebhookRegistration(**dict(row)) if row else None


async def list_registrations(
    db: AsyncSession,
    tenant_id: UUID,
) -> list[WebhookRegistration]:
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, source, signing_secret, description, active, created_at
            FROM integration.webhook_registrations
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            """
        ),
        {"tenant_id": str(tenant_id)},
    )
    return [WebhookRegistration(**dict(row)) for row in result.mappings().all()]


async def delete_registration(
    db: AsyncSession,
    registration_id: UUID,
    tenant_id: UUID,
) -> bool:
    result = await db.execute(
        text(
            """
            DELETE FROM integration.webhook_registrations
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": str(registration_id), "tenant_id": str(tenant_id)},
    )
    await db.commit()
    return result.rowcount > 0


# ── Ingestion pipeline ─────────────────────────────────────────────────────────

async def _load_active_registration(
    db: AsyncSession,
    registration_id: UUID,
) -> WebhookRegistration:
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, source, signing_secret, description, active, created_at
            FROM integration.webhook_registrations
            WHERE id = :id AND active = TRUE
            """
        ),
        {"id": str(registration_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise WebhookNotFoundError(f"No active registration {registration_id}")
    return WebhookRegistration(**dict(row))


def _infer_event_type(raw_type: str) -> WebhookEventType:
    mapping: dict[str, WebhookEventType] = {
        "supplier.updated": WebhookEventType.SUPPLIER_UPDATED,
        "supplier.created": WebhookEventType.SUPPLIER_CREATED,
        "purchase_order.created": WebhookEventType.PURCHASE_ORDER_CREATED,
        "purchase_order.updated": WebhookEventType.PURCHASE_ORDER_UPDATED,
        "invoice.received": WebhookEventType.INVOICE_RECEIVED,
        "delivery.confirmed": WebhookEventType.DELIVERY_CONFIRMED,
        "risk.alert": WebhookEventType.RISK_ALERT,
    }
    return mapping.get(raw_type.lower(), WebhookEventType.UNKNOWN)


def _extract_entity(
    event_type: WebhookEventType,
    data: dict[str, Any],
) -> tuple[str, str]:
    """Return (entity_type, entity_id) from raw payload."""
    if event_type in (WebhookEventType.SUPPLIER_CREATED, WebhookEventType.SUPPLIER_UPDATED):
        return "supplier", str(data.get("supplier_id", data.get("id", "")))
    if event_type in (
        WebhookEventType.PURCHASE_ORDER_CREATED, WebhookEventType.PURCHASE_ORDER_UPDATED
    ):
        return "purchase_order", str(data.get("purchase_order_id", data.get("id", "")))
    if event_type == WebhookEventType.INVOICE_RECEIVED:
        return "invoice", str(data.get("invoice_id", data.get("id", "")))
    if event_type == WebhookEventType.DELIVERY_CONFIRMED:
        return "delivery", str(data.get("delivery_id", data.get("id", "")))
    return "unknown", str(data.get("id", ""))


async def ingest_webhook(
    db: AsyncSession,
    rate_limiter: SlidingWindowRateLimiter,
    registration_id: UUID,
    body: bytes,
    signature_header: str | None,
    event_id: str | None = None,
) -> WebhookDeliveryLog:
    """
    Full ingest pipeline:
    1. Load registration + verify HMAC
    2. Rate-limit check (per tenant)
    3. Parse payload
    4. Normalise to :class:`NormalisedEvent`
    5. Publish to Kafka
    6. Persist delivery log
    """
    reg = await _load_active_registration(db, registration_id)

    # 1. Signature verification
    sig_valid = False
    if signature_header:
        sig_valid = verify_webhook_signature(body, signature_header, reg.signing_secret)
    else:
        logger.warning("Webhook %s received without signature header", registration_id)

    if not sig_valid:
        raise WebhookSignatureError(
            f"Webhook signature invalid for registration {registration_id}"
        )

    # 2. Rate limit
    rl_key = f"{reg.tenant_id}:{reg.source}"
    await rate_limiter.check(rl_key)

    # 3. Parse
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Webhook body is not valid JSON: {exc}") from exc

    occurred_str = raw.get("occurred_at") or raw.get("timestamp") or datetime.utcnow().isoformat()
    try:
        occurred_at = datetime.fromisoformat(str(occurred_str))
    except ValueError:
        occurred_at = datetime.utcnow()

    inbound = InboundWebhookPayload(
        source=reg.source,
        event_type=raw.get("event_type", "unknown"),
        event_id=event_id or str(raw.get("event_id", str(uuid4()))),
        tenant_id=reg.tenant_id,
        occurred_at=occurred_at,
        data=raw.get("data", raw),
    )

    # 4. Normalise
    normalised_type = _infer_event_type(inbound.event_type)
    entity_type, entity_id = _extract_entity(normalised_type, inbound.data)
    normalised = NormalisedEvent(
        event_id=inbound.event_id,
        event_type=normalised_type,
        source=inbound.source,
        tenant_id=inbound.tenant_id,
        occurred_at=inbound.occurred_at,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=inbound.data,
    )

    # 5. Publish
    kafka_offset = await publish_webhook_event(
        normalised.model_dump(mode="json"),
        tenant_id=str(inbound.tenant_id),
    )

    # 6. Persist log
    log = await _persist_delivery_log(
        db,
        registration_id=registration_id,
        event_id=inbound.event_id,
        event_type=inbound.event_type,
        signature_valid=sig_valid,
        processed=kafka_offset is not None,
        kafka_offset=kafka_offset,
    )
    return log


async def _persist_delivery_log(
    db: AsyncSession,
    *,
    registration_id: UUID,
    event_id: str,
    event_type: str,
    signature_valid: bool,
    processed: bool,
    kafka_offset: int | None,
    error: str | None = None,
) -> WebhookDeliveryLog:
    result = await db.execute(
        text(
            """
            INSERT INTO integration.webhook_delivery_logs
                (registration_id, event_id, event_type, signature_valid,
                 processed, kafka_offset, error)
            VALUES
                (:registration_id, :event_id, :event_type, :signature_valid,
                 :processed, :kafka_offset, :error)
            RETURNING id, registration_id, event_id, event_type, received_at,
                      signature_valid, processed, kafka_offset, error
            """
        ),
        {
            "registration_id": str(registration_id),
            "event_id": event_id,
            "event_type": event_type,
            "signature_valid": signature_valid,
            "processed": processed,
            "kafka_offset": kafka_offset,
            "error": error,
        },
    )
    await db.commit()
    return WebhookDeliveryLog(**dict(result.mappings().one()))
