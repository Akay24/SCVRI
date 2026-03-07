"""Celery tasks for the Integration service."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import Task

from integration.workers.celery_app import app

logger = logging.getLogger(__name__)


def _run(coro: Any) -> Any:
    """Run a coroutine from a synchronous Celery task."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── ERP scheduled sync ─────────────────────────────────────────────────────────

@app.task(
    name="integration.workers.tasks.scheduled_erp_sync_all_tenants",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def scheduled_erp_sync_all_tenants(self: Task) -> dict[str, Any]:
    """
    Triggered every 6 hours by Beat.

    Queries ``integration.erp_connections`` for all active connection configs
    and dispatches an individual :func:`sync_erp_tenant` task per connection.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    from scvri_shared.config import get_settings
    from integration.schemas.erp import ERPSystem, ERPEntityType

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async def _query() -> list[dict]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    "SELECT tenant_id, system FROM integration.erp_connections WHERE active = TRUE"
                )
            )
            return [dict(r) for r in result.mappings().all()]

    try:
        connections = _run(_query())
        dispatched = 0
        entity_types = [e.value for e in ERPEntityType]
        since = (datetime.now(tz=timezone.utc) - timedelta(hours=7)).isoformat()

        for conn in connections:
            for entity_type in entity_types:
                sync_erp_tenant.apply_async(
                    kwargs={
                        "tenant_id": str(conn["tenant_id"]),
                        "system": conn["system"],
                        "entity_type": entity_type,
                        "since": since,
                    }
                )
                dispatched += 1

        logger.info("Dispatched %d ERP sync tasks", dispatched)
        return {"dispatched": dispatched}
    except Exception as exc:
        logger.error("scheduled_erp_sync_all_tenants failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="integration.workers.tasks.sync_erp_tenant",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def sync_erp_tenant(
    self: Task,
    *,
    tenant_id: str,
    system: str,
    entity_type: str,
    since: str | None = None,
) -> dict[str, Any]:
    """Pull one entity type from one tenant's ERP and publish to Kafka."""
    from uuid import UUID
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from scvri_shared.config import get_settings
    from integration.schemas.erp import ERPEntityType, ERPPullRequest, ERPSystem
    from integration.services.erp_service import sync_erp_entities

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async def _sync() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            request = ERPPullRequest(
                tenant_id=UUID(tenant_id),
                system=ERPSystem(system),
                entity_type=ERPEntityType(entity_type),
                since=datetime.fromisoformat(since) if since else None,
            )
            result = await sync_erp_entities(db, request)
            return result.model_dump()

    try:
        return _run(_sync())
    except Exception as exc:
        logger.error("sync_erp_tenant failed: tenant=%s system=%s entity=%s: %s",
                     tenant_id, system, entity_type, exc)
        raise self.retry(exc=exc)


# ── Retry failed outbound deliveries ──────────────────────────────────────────

@app.task(
    name="integration.workers.tasks.retry_failed_outbound_deliveries",
    bind=True,
    max_retries=1,
)
def retry_failed_outbound_deliveries(self: Task) -> dict[str, Any]:
    """
    Pick up outbound delivery attempts in FAILED state (attempt < retry_max)
    and re-queue them for delivery.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    from scvri_shared.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async def _fetch_and_retry() -> int:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    """
                    SELECT a.id, a.endpoint_id, a.event_id, a.event_type,
                           a.attempt_number, e.retry_max,
                           e.url, e.secret, e.timeout_seconds, e.tenant_id,
                           e.name, e.event_types, e.active
                    FROM integration.outbound_delivery_attempts a
                    JOIN integration.outbound_endpoints e ON e.id = a.endpoint_id
                    WHERE a.status = 'failed'
                      AND a.attempt_number < e.retry_max
                      AND a.scheduled_at > NOW() - INTERVAL '24 hours'
                    LIMIT 100
                    """
                )
            )
            rows = result.mappings().all()
            retried = 0
            for row in rows:
                retry_outbound_delivery.apply_async(
                    kwargs=dict(row),
                    countdown=min(60 * (2 ** row["attempt_number"]), 1800),
                )
                retried += 1
            return retried

    try:
        retried = _run(_fetch_and_retry())
        logger.info("Queued %d outbound delivery retries", retried)
        return {"retried": retried}
    except Exception as exc:
        logger.error("retry_failed_outbound_deliveries failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(
    name="integration.workers.tasks.retry_outbound_delivery",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def retry_outbound_delivery(self: Task, **kwargs: Any) -> dict[str, Any]:
    """Retry a single failed outbound delivery attempt."""
    import json
    from uuid import UUID
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from scvri_shared.config import get_settings
    from integration.schemas.outbound import (
        OutboundEndpoint, OutboundEventType, OutboundPushPayload,
    )
    from integration.services.outbound_service import _deliver_to_endpoint, _persist_attempt

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async def _retry() -> dict[str, Any]:
        event_types = kwargs.get("event_types", [])
        if isinstance(event_types, str):
            event_types = json.loads(event_types)

        endpoint = OutboundEndpoint(
            id=UUID(str(kwargs["endpoint_id"])),
            tenant_id=UUID(str(kwargs["tenant_id"])),
            name=kwargs["name"],
            url=kwargs["url"],
            secret=kwargs["secret"],
            event_types=[OutboundEventType(e) for e in event_types],
            active=kwargs.get("active", True),
            timeout_seconds=kwargs.get("timeout_seconds", 10),
            retry_max=kwargs.get("retry_max", 3),
        )
        # Reconstruct a minimal payload from stored attempt data
        payload = OutboundPushPayload(
            event_id=kwargs["event_id"],
            event_type=OutboundEventType(kwargs["event_type"]),
            tenant_id=endpoint.tenant_id,
            occurred_at=datetime.now(tz=timezone.utc),
            entity_type="unknown",
            entity_id="unknown",
        )
        attempt = await _deliver_to_endpoint(
            endpoint, payload, attempt_number=kwargs["attempt_number"] + 1
        )
        async with AsyncSessionLocal() as db:
            await _persist_attempt(db, attempt)
        return attempt.model_dump(mode="json")

    try:
        return _run(_retry())
    except Exception as exc:
        logger.error("retry_outbound_delivery failed: event_id=%s: %s",
                     kwargs.get("event_id"), exc)
        raise self.retry(exc=exc)


# ── Purge old logs ─────────────────────────────────────────────────────────────

@app.task(
    name="integration.workers.tasks.purge_old_delivery_logs",
    bind=True,
    max_retries=1,
)
def purge_old_delivery_logs(self: Task, retention_days: int = 90) -> dict[str, Any]:
    """Delete webhook delivery logs and outbound attempt records older than *retention_days*."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    from scvri_shared.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async def _purge() -> dict[str, int]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
        async with AsyncSessionLocal() as db:
            r1 = await db.execute(
                text(
                    "DELETE FROM integration.webhook_delivery_logs WHERE received_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            r2 = await db.execute(
                text(
                    "DELETE FROM integration.outbound_delivery_attempts WHERE scheduled_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            await db.commit()
            return {"webhook_logs_deleted": r1.rowcount, "outbound_attempts_deleted": r2.rowcount}

    try:
        result = _run(_purge())
        logger.info("Purged delivery logs: %s", result)
        return result
    except Exception as exc:
        logger.error("purge_old_delivery_logs failed: %s", exc)
        raise self.retry(exc=exc)
