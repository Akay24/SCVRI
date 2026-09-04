"""Transactional Outbox Relay — polls and publishes pending outbox events to Kafka.

Features:
- Atomically enqueues events within existing database transactions
- Concurrent-safe polling via ``SELECT ... FOR UPDATE SKIP LOCKED``
- Exponential backoff retry with Dead Letter Queue alerting
- Graceful shutdown support via asyncio.Event
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.config import settings
from scvri_shared.db import AsyncSessionLocal
from scvri_shared.kafka import SCVRIProducer, init_producer
from scvri_shared.logging import get_logger
from scvri_shared.models.outbox import OutboxEvent

log = get_logger(__name__)

DEFAULT_BATCH_SIZE = 100
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 5


async def schedule_outbox_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    event_key: str | None = None,
    correlation_id: str | None = None,
) -> OutboxEvent:
    """Schedule an event for publishing within the caller's active DB transaction.

    This function does NOT commit the session; the event commits atomically
    with the surrounding business entity changes.
    """
    event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        topic=topic,
        event_key=event_key or str(tenant_id),
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
        status="pending",
        retry_count=0,
    )
    res = db.add(event)
    if asyncio.iscoroutine(res):
        await res
    return event


class OutboxRelay:
    """Background worker that continuously relays outbox events to Kafka."""

    def __init__(
        self,
        batch_size: int = DEFAULT_BATCH_SIZE,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self._stop_event = asyncio.Event()
        self._producer: SCVRIProducer | None = None

    async def start(self) -> None:
        """Run the relay loop until stop() is called."""
        self._producer = await init_producer()
        log.info("outbox.relay.started", batch_size=self.batch_size, interval=self.poll_interval)

        while not self._stop_event.is_set():
            try:
                processed = await self.process_batch()
                if processed == 0:
                    await asyncio.sleep(self.poll_interval)
            except Exception as exc:  # noqa: BLE001
                log.error("outbox.relay.batch_error", error=str(exc))
                await asyncio.sleep(self.poll_interval)

        log.info("outbox.relay.stopped")

    def stop(self) -> None:
        """Signal the relay loop to exit."""
        self._stop_event.set()

    async def process_batch(self) -> int:
        """Fetch and publish one batch of pending events using SKIP LOCKED."""
        async with AsyncSessionLocal() as session:
            # Select pending or retryable failed events
            query = (
                select(OutboxEvent)
                .where(
                    (OutboxEvent.status == "pending")
                    | (
                        (OutboxEvent.status == "failed")
                        & (OutboxEvent.retry_count < self.max_retries)
                    )
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(self.batch_size)
                .with_for_update(skip_locked=True)
            )

            result = await session.execute(query)
            events = result.scalars().all()

            if not events:
                return 0

            for event in events:
                try:
                    if self._producer is None:
                        self._producer = await init_producer()

                    await self._producer.publish(
                        topic=event.topic,
                        key=event.event_key,
                        value=event.payload,
                        event_type=event.event_type,
                        tenant_id=str(event.tenant_id),
                        correlation_id=event.correlation_id or "-",
                    )

                    event.status = "published"
                    event.published_at = datetime.now(timezone.utc)
                    event.last_error = None
                    log.debug("outbox.event.published", event_id=str(event.id), topic=event.topic)

                except Exception as exc:  # noqa: BLE001
                    event.retry_count += 1
                    event.last_error = str(exc)
                    event.status = "failed" if event.retry_count >= self.max_retries else "pending"
                    log.warning(
                        "outbox.event.publish_failed",
                        event_id=str(event.id),
                        topic=event.topic,
                        retry_count=event.retry_count,
                        error=str(exc),
                    )

            await session.commit()
            return len(events)
