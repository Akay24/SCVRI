"""Outbound push service — deliver SCVRI events to external systems."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from integration.core.circuit_breaker import get_circuit_breaker, with_retry
from integration.core.rate_limiter import (
    OUTBOUND_RATE_LIMIT,
    OUTBOUND_RATE_WINDOW,
    RateLimitExceeded,
    SlidingWindowRateLimiter,
)
from integration.schemas.outbound import (
    DeliveryStatus,
    OutboundDeliveryAttempt,
    OutboundEndpoint,
    OutboundEventType,
    OutboundPushPayload,
    OutboundPushRequest,
    OutboundPushResult,
)

logger = logging.getLogger(__name__)


# ── Endpoint CRUD ──────────────────────────────────────────────────────────────

async def create_endpoint(
    db: AsyncSession,
    endpoint: OutboundEndpoint,
) -> OutboundEndpoint:
    result = await db.execute(
        text(
            """
            INSERT INTO integration.outbound_endpoints
                (tenant_id, name, url, secret, event_types, active, timeout_seconds, retry_max)
            VALUES
                (:tenant_id, :name, :url, :secret, :event_types::jsonb,
                 :active, :timeout_seconds, :retry_max)
            RETURNING id, tenant_id, name, url, secret, event_types,
                      active, timeout_seconds, retry_max, created_at
            """
        ),
        {
            "tenant_id": str(endpoint.tenant_id),
            "name": endpoint.name,
            "url": endpoint.url,
            "secret": endpoint.secret,
            "event_types": json.dumps([e.value for e in endpoint.event_types]),
            "active": endpoint.active,
            "timeout_seconds": endpoint.timeout_seconds,
            "retry_max": endpoint.retry_max,
        },
    )
    await db.commit()
    row = dict(result.mappings().one())
    row["event_types"] = json.loads(row["event_types"]) if isinstance(row["event_types"], str) else row["event_types"]
    return OutboundEndpoint(**row)


async def list_endpoints(
    db: AsyncSession,
    tenant_id: UUID,
) -> list[OutboundEndpoint]:
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, name, url, secret, event_types, active,
                   timeout_seconds, retry_max, created_at
            FROM integration.outbound_endpoints
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            """
        ),
        {"tenant_id": str(tenant_id)},
    )
    endpoints = []
    for row in result.mappings().all():
        d = dict(row)
        d["event_types"] = json.loads(d["event_types"]) if isinstance(d["event_types"], str) else d["event_types"]
        endpoints.append(OutboundEndpoint(**d))
    return endpoints


async def delete_endpoint(
    db: AsyncSession,
    endpoint_id: UUID,
    tenant_id: UUID,
) -> bool:
    result = await db.execute(
        text(
            """
            DELETE FROM integration.outbound_endpoints
            WHERE id = :id AND tenant_id = :tenant_id
            """
        ),
        {"id": str(endpoint_id), "tenant_id": str(tenant_id)},
    )
    await db.commit()
    return result.rowcount > 0


async def _load_matching_endpoints(
    db: AsyncSession,
    tenant_id: UUID,
    event_type: OutboundEventType,
) -> list[OutboundEndpoint]:
    """Return active endpoints subscribed to *event_type* for the tenant."""
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, name, url, secret, event_types, active,
                   timeout_seconds, retry_max, created_at
            FROM integration.outbound_endpoints
            WHERE tenant_id = :tenant_id
              AND active = TRUE
              AND (event_types = '[]'::jsonb OR event_types @> :event_type::jsonb)
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "event_type": json.dumps([event_type.value]),
        },
    )
    endpoints = []
    for row in result.mappings().all():
        d = dict(row)
        d["event_types"] = json.loads(d["event_types"]) if isinstance(d["event_types"], str) else d["event_types"]
        endpoints.append(OutboundEndpoint(**d))
    return endpoints


# ── Delivery ───────────────────────────────────────────────────────────────────

def _sign_payload(body: bytes, secret: str) -> str:
    """Return ``sha256=<hex>`` HMAC signature for the outbound payload."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _deliver_to_endpoint(
    endpoint: OutboundEndpoint,
    payload: OutboundPushPayload,
    attempt_number: int = 1,
) -> OutboundDeliveryAttempt:
    body = payload.model_dump_json().encode()
    signature = _sign_payload(body, endpoint.secret)

    attempt = OutboundDeliveryAttempt(
        endpoint_id=endpoint.id,  # type: ignore[arg-type]
        event_id=payload.event_id,
        event_type=payload.event_type,
        attempt_number=attempt_number,
        scheduled_at=datetime.now(tz=timezone.utc),
        status=DeliveryStatus.PENDING,
    )

    breaker = get_circuit_breaker(f"outbound:{endpoint.id}")

    async def _post() -> tuple[int, str]:
        async with httpx.AsyncClient(timeout=endpoint.timeout_seconds) as client:
            resp = await client.post(
                endpoint.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-SCVRI-Signature": signature,
                    "X-SCVRI-Event-ID": payload.event_id,
                    "X-SCVRI-Event-Type": payload.event_type.value,
                },
            )
            return resp.status_code, resp.text[:500]

    try:
        status_code, response_body = await breaker.call(
            with_retry,
            _post,
            max_attempts=attempt_number,  # don't retry internally; Celery handles retries
            wait_min=0.5,
            wait_max=5.0,
        )
        attempt.delivered_at = datetime.now(tz=timezone.utc)
        attempt.response_code = status_code
        attempt.response_body = response_body
        attempt.status = (
            DeliveryStatus.DELIVERED if 200 <= status_code < 300 else DeliveryStatus.FAILED
        )
        if attempt.status == DeliveryStatus.FAILED:
            logger.warning(
                "Outbound delivery failed: endpoint=%s event=%s status=%d",
                endpoint.id, payload.event_id, status_code,
            )
    except Exception as exc:
        attempt.status = DeliveryStatus.FAILED
        attempt.error = str(exc)
        logger.error(
            "Outbound delivery error: endpoint=%s event=%s error=%s",
            endpoint.id, payload.event_id, exc,
        )

    return attempt


async def push_event(
    db: AsyncSession,
    rate_limiter: SlidingWindowRateLimiter,
    request: OutboundPushRequest,
) -> OutboundPushResult:
    """
    Deliver an event to all active matching endpoints for the tenant.

    - Rate-limits per endpoint
    - Uses circuit breaker per endpoint
    - Persists delivery attempt records
    """
    event_id = str(uuid4())
    payload = OutboundPushPayload(
        event_id=event_id,
        event_type=request.event_type,
        tenant_id=request.tenant_id,
        occurred_at=datetime.now(tz=timezone.utc),
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        data=request.data,
    )

    endpoints = await _load_matching_endpoints(db, request.tenant_id, request.event_type)
    delivered = 0
    failed = 0

    for endpoint in endpoints:
        try:
            await rate_limiter.check(str(endpoint.id))
        except RateLimitExceeded:
            logger.warning("Rate limit exceeded for outbound endpoint %s", endpoint.id)
            failed += 1
            continue

        attempt = await _deliver_to_endpoint(endpoint, payload)
        await _persist_attempt(db, attempt)

        if attempt.status == DeliveryStatus.DELIVERED:
            delivered += 1
        else:
            failed += 1

    return OutboundPushResult(
        event_id=event_id,
        endpoints_targeted=len(endpoints),
        delivered=delivered,
        failed=failed,
    )


async def _persist_attempt(
    db: AsyncSession,
    attempt: OutboundDeliveryAttempt,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO integration.outbound_delivery_attempts
                (endpoint_id, event_id, event_type, attempt_number,
                 scheduled_at, delivered_at, status, response_code, response_body, error)
            VALUES
                (:endpoint_id, :event_id, :event_type, :attempt_number,
                 :scheduled_at, :delivered_at, :status, :response_code, :response_body, :error)
            """
        ),
        {
            "endpoint_id": str(attempt.endpoint_id),
            "event_id": attempt.event_id,
            "event_type": attempt.event_type.value,
            "attempt_number": attempt.attempt_number,
            "scheduled_at": attempt.scheduled_at,
            "delivered_at": attempt.delivered_at,
            "status": attempt.status.value,
            "response_code": attempt.response_code,
            "response_body": attempt.response_body,
            "error": attempt.error,
        },
    )
    await db.commit()


async def list_delivery_attempts(
    db: AsyncSession,
    tenant_id: UUID,
    endpoint_id: UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters = "WHERE e.tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": limit}
    if endpoint_id:
        filters += " AND a.endpoint_id = :endpoint_id"
        params["endpoint_id"] = str(endpoint_id)

    result = await db.execute(
        text(
            f"""
            SELECT a.id, a.endpoint_id, e.name AS endpoint_name,
                   a.event_id, a.event_type, a.attempt_number,
                   a.scheduled_at, a.delivered_at, a.status,
                   a.response_code, a.error
            FROM integration.outbound_delivery_attempts a
            JOIN integration.outbound_endpoints e ON e.id = a.endpoint_id
            {filters}
            ORDER BY a.scheduled_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]
