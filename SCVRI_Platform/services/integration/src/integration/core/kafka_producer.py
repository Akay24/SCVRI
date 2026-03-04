"""Async Kafka producer wrapper (aiokafka)."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from scvri_shared.config import get_settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None

# ── Topic names ────────────────────────────────────────────────────────────────
TOPIC_ERP_EVENTS = "integration.erp.events"
TOPIC_WEBHOOK_EVENTS = "integration.webhook.events"
TOPIC_OUTBOUND_DELIVERIES = "integration.outbound.deliveries"
TOPIC_SUPPLIER_SYNC = "supplier.sync"
TOPIC_RISK_EVENTS = "risk.events"


def _serialise(value: Any) -> bytes:
    def _default(obj: Any) -> Any:
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")

    return json.dumps(value, default=_default).encode("utf-8")


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        settings = get_settings()
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=_serialise,
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
            compression_type="gzip",
            enable_idempotence=True,
            acks="all",
            max_batch_size=65536,
            linger_ms=5,
        )
        await _producer.start()
        logger.info("Kafka producer started (brokers=%s)", settings.kafka_bootstrap_servers)
    return _producer


async def stop_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
        logger.info("Kafka producer stopped")


async def publish(
    topic: str,
    value: dict[str, Any],
    *,
    key: str | None = None,
    headers: dict[str, str] | None = None,
) -> int | None:
    """
    Publish a single message to *topic*.

    Returns the Kafka partition offset, or ``None`` if send failed
    (error is logged but not re-raised so callers do not crash on
    transient broker unavailability).
    """
    try:
        producer = await get_producer()
        encoded_headers = (
            [(k, v.encode("utf-8")) for k, v in headers.items()]
            if headers
            else None
        )
        record_metadata = await producer.send_and_wait(
            topic,
            value=value,
            key=key,
            headers=encoded_headers,
        )
        logger.debug(
            "Published to %s partition=%d offset=%d",
            topic, record_metadata.partition, record_metadata.offset,
        )
        return record_metadata.offset
    except KafkaError as exc:
        logger.error("Failed to publish to Kafka topic %s: %s", topic, exc)
        return None


async def publish_erp_event(event: dict[str, Any], *, tenant_id: str) -> int | None:
    return await publish(
        TOPIC_ERP_EVENTS,
        event,
        key=tenant_id,
        headers={"source": "erp", "tenant_id": tenant_id},
    )


async def publish_webhook_event(event: dict[str, Any], *, tenant_id: str) -> int | None:
    return await publish(
        TOPIC_WEBHOOK_EVENTS,
        event,
        key=tenant_id,
        headers={"source": "webhook", "tenant_id": tenant_id},
    )


async def publish_outbound_delivery(task: dict[str, Any], *, endpoint_id: str) -> int | None:
    return await publish(
        TOPIC_OUTBOUND_DELIVERIES,
        task,
        key=endpoint_id,
        headers={"source": "outbound"},
    )
