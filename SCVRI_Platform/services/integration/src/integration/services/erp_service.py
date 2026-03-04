"""ERP pull-sync service — pull entities from ERP, normalise, publish to Kafka."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from integration.connectors import get_connector
from integration.core.circuit_breaker import get_circuit_breaker, with_retry
from integration.core.kafka_producer import publish_erp_event
from integration.schemas.erp import (
    ERPConnectionConfig,
    ERPEntityType,
    ERPPullRequest,
    ERPRawEvent,
    ERPSyncResult,
    ERPSystem,
)

logger = logging.getLogger(__name__)


async def get_erp_config(
    db: AsyncSession,
    tenant_id: UUID,
    system: ERPSystem,
) -> ERPConnectionConfig | None:
    """Load ERP connection config from ``integration.erp_connections``."""
    result = await db.execute(
        text(
            """
            SELECT system, base_url, client_id, client_secret,
                   tenant_id, timeout_seconds, extra
            FROM integration.erp_connections
            WHERE tenant_id = :tenant_id AND system = :system AND active = TRUE
            """
        ),
        {"tenant_id": str(tenant_id), "system": system.value},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    return ERPConnectionConfig(**dict(row))


async def sync_erp_entities(
    db: AsyncSession,
    request: ERPPullRequest,
) -> ERPSyncResult:
    """
    Pull a page of entities from the tenant's ERP and publish them to Kafka.

    Uses a circuit breaker (per system) + tenacity retry for resilience.
    """
    start = time.monotonic()
    config = await get_erp_config(db, request.tenant_id, request.system)
    if config is None:
        raise ValueError(
            f"No active ERP connection for tenant {request.tenant_id} / {request.system}"
        )

    breaker = get_circuit_breaker(f"erp:{request.system}")
    fetched = 0
    published = 0
    errors = 0

    async def _do_pull() -> list[ERPRawEvent]:
        async with get_connector(config) as connector:
            return await connector.pull_all(
                request.entity_type,
                since=request.since,
                page_size=request.page_size,
            )

    events = await breaker.call(
        with_retry,
        _do_pull,
        max_attempts=3,
        wait_min=2.0,
        wait_max=15.0,
    )
    fetched = len(events)

    for event in events:
        offset = await publish_erp_event(
            event.model_dump(mode="json"),
            tenant_id=str(event.tenant_id),
        )
        if offset is not None:
            published += 1
        else:
            errors += 1

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "ERP sync complete: tenant=%s system=%s entity=%s "
        "fetched=%d published=%d errors=%d duration=%dms",
        request.tenant_id, request.system, request.entity_type,
        fetched, published, errors, duration_ms,
    )
    return ERPSyncResult(
        tenant_id=request.tenant_id,
        system=request.system,
        entity_type=request.entity_type,
        fetched=fetched,
        published=published,
        errors=errors,
        duration_ms=duration_ms,
    )


async def list_erp_connections(
    db: AsyncSession,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT id, system, base_url, timeout_seconds, active, created_at
            FROM integration.erp_connections
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            """
        ),
        {"tenant_id": str(tenant_id)},
    )
    return [dict(row) for row in result.mappings().all()]


async def upsert_erp_connection(
    db: AsyncSession,
    config: ERPConnectionConfig,
) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            INSERT INTO integration.erp_connections
                (tenant_id, system, base_url, client_id, client_secret, timeout_seconds, extra)
            VALUES
                (:tenant_id, :system, :base_url, :client_id, :client_secret,
                 :timeout_seconds, :extra::jsonb)
            ON CONFLICT (tenant_id, system)
            DO UPDATE SET
                base_url = EXCLUDED.base_url,
                client_id = EXCLUDED.client_id,
                client_secret = EXCLUDED.client_secret,
                timeout_seconds = EXCLUDED.timeout_seconds,
                extra = EXCLUDED.extra,
                active = TRUE,
                updated_at = NOW()
            RETURNING id, tenant_id, system, base_url, active, created_at
            """
        ),
        {
            "tenant_id": str(config.tenant_id),
            "system": config.system.value,
            "base_url": config.base_url,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "timeout_seconds": config.timeout_seconds,
            "extra": __import__("json").dumps(config.extra),
        },
    )
    await db.commit()
    return dict(result.mappings().one())
