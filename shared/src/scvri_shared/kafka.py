"""Kafka producer and consumer helpers for the SCVRI platform.

Every message is wrapped in a standard EventEnvelope before serialisation,
giving all events a consistent schema regardless of which service emits them.

Usage — Producer:
    from scvri_shared.kafka import get_producer, EventEnvelope

    async with get_producer() as producer:
        await producer.publish(
            topic="supplier.events",
            key=str(tenant_id),
            value={"event": "supplier.created", "supplier_id": str(s.id)},
        )

Usage — Consumer:
    from scvri_shared.kafka import SCVRIConsumer

    consumer = SCVRIConsumer(
        topics=["supplier.events"],
        group_id="risk-engine-supplier-consumer",
        handler=my_async_handler,
    )
    await consumer.start()
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Coroutine

from scvri_shared.config import settings
from scvri_shared.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Event Envelope — canonical schema for all SCVRI Kafka messages
# ---------------------------------------------------------------------------
@dataclass
class EventEnvelope:
    """Standard cloud-events–inspired wrapper for all SCVRI Kafka messages.

    Attributes:
        event_id:       Globally unique event UUID (idempotency key).
        event_type:     Dot-separated event name, e.g. ``supplier.status.changed``.
        spec_version:   Envelope schema version — increment when shape changes.
        source_service: Service that emitted the event, e.g. ``supplier-management``.
        tenant_id:      Tenant the event belongs to.
        correlation_id: Request correlation ID — propagated from HTTP X-Correlation-ID.
        timestamp:      UTC ISO-8601 emission time.
        payload:        Arbitrary event-specific data.
        version:        Payload schema version — for consumer-driven contract testing.
    """

    event_type: str
    tenant_id: str
    payload: dict[str, Any]
    source_service: str = field(default_factory=lambda: settings.service_name)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spec_version: str = "1.0"
    correlation_id: str = "-"
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )
    version: str = "1"

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "EventEnvelope":
        data = json.loads(raw.decode("utf-8"))
        return cls(**data)


# ---------------------------------------------------------------------------
# SASL config helper
# ---------------------------------------------------------------------------
def _sasl_kwargs() -> dict[str, Any]:
    """Return aiokafka SASL keyword arguments for MSK SASL/SCRAM-SHA-512."""
    if not settings.kafka_sasl_username:
        return {}
    return {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": settings.kafka_sasl_mechanism,
        "sasl_plain_username": settings.kafka_sasl_username,
        "sasl_plain_password": settings.kafka_sasl_password.get_secret_value(),
    }


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------
_DEFAULT_ACKS = "all"
_DEFAULT_COMPRESSION = "lz4"
_DEFAULT_MAX_BATCH_BYTES = 1_048_576  # 1 MB
_PRODUCER_SINGLETON: "SCVRIProducer | None" = None


class SCVRIProducer:
    """Thin aiokafka producer wrapper.

    Features:
    - Automatic EventEnvelope wrapping
    - Dead Letter Queue (DLQ) routing on publish failures
    - Configurable retry with exponential back-off
    - Graceful start/stop lifecycle
    """

    def __init__(self) -> None:
        from aiokafka import AIOKafkaProducer  # noqa: PLC0415

        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            acks=_DEFAULT_ACKS,
            compression_type=_DEFAULT_COMPRESSION,
            max_batch_size=_DEFAULT_MAX_BATCH_BYTES,
            request_timeout_ms=30_000,
            retry_backoff_ms=500,
            enable_idempotence=True,
            **_sasl_kwargs(),
        )
        self._started = False

    async def start(self) -> None:
        if not self._started:
            await self._producer.start()
            self._started = True
            log.info("kafka.producer.started", brokers=settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._started:
            await self._producer.stop()
            self._started = False
            log.info("kafka.producer.stopped")

    async def send(
        self,
        *,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        tenant_id: str | None = None,
        key: str | None = None,
        correlation_id: str = "-",
        **kwargs: Any,
    ) -> None:
        """Alias for publish to support send() callers across services."""
        await self.publish(
            topic=topic,
            key=key or tenant_id or "default",
            value=payload,
            event_type=event_type,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            **kwargs,
        )

    async def publish(
        self,
        *,
        topic: str,
        key: str,
        value: dict[str, Any],
        event_type: str | None = None,
        tenant_id: str | None = None,
        correlation_id: str = "-",
        retries: int = 3,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        """Publish *value* to *topic*, wrapped in an EventEnvelope.

        Falls back to a ``<topic>.dlq`` topic after *retries* failures.
        """
        from scvri_shared.logging import correlation_id_ctx, tenant_id_ctx  # noqa: PLC0415

        resolved_correlation_id = correlation_id or correlation_id_ctx.get("-")
        resolved_tenant_id = tenant_id or tenant_id_ctx.get("-")

        envelope = EventEnvelope(
            event_type=event_type or topic,
            tenant_id=resolved_tenant_id,
            payload=value,
            correlation_id=resolved_correlation_id,
        )
        raw = envelope.to_json()
        raw_key = key.encode("utf-8")

        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                await self._producer.send_and_wait(topic, value=raw, key=raw_key)
                log.debug(
                    "kafka.published",
                    topic=topic,
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = backoff_base_seconds * (2 ** (attempt - 1))
                log.warning(
                    "kafka.publish_retry",
                    topic=topic,
                    attempt=attempt,
                    max_retries=retries,
                    error=str(exc),
                    backoff_seconds=wait,
                )
                await asyncio.sleep(wait)

        # All retries exhausted — route to DLQ
        dlq_topic = f"{topic}.dlq"
        try:
            dlq_envelope = EventEnvelope(
                event_type=f"dlq.{event_type or topic}",
                tenant_id=resolved_tenant_id,
                payload={"original_payload": value, "error": str(last_exc)},
                correlation_id=resolved_correlation_id,
            )
            await self._producer.send_and_wait(dlq_topic, value=dlq_envelope.to_json(), key=raw_key)
            log.error(
                "kafka.dlq_routed",
                topic=topic,
                dlq_topic=dlq_topic,
                error=str(last_exc),
            )
        except Exception as dlq_exc:  # noqa: BLE001
            log.critical("kafka.dlq_failed", topic=topic, error=str(dlq_exc))
        raise RuntimeError(f"Failed to publish to {topic} after {retries} retries: {last_exc}") from last_exc


@asynccontextmanager
async def get_producer() -> AsyncIterator[SCVRIProducer]:
    """Context-manager that returns a started producer and stops it on exit.

    For long-lived applications prefer the singleton accessor below.
    """
    p = SCVRIProducer()
    await p.start()
    try:
        yield p
    finally:
        await p.stop()


async def init_producer() -> SCVRIProducer:
    """Initialise the module-level singleton producer.

    Call this in the FastAPI ``lifespan`` startup hook and store the result on
    ``app.state.kafka_producer``.
    """
    global _PRODUCER_SINGLETON  # noqa: PLW0603
    if _PRODUCER_SINGLETON is None:
        _PRODUCER_SINGLETON = SCVRIProducer()
        await _PRODUCER_SINGLETON.start()
    return _PRODUCER_SINGLETON


async def close_producer() -> None:
    """Stop the module-level singleton producer on application shutdown."""
    global _PRODUCER_SINGLETON  # noqa: PLW0603
    if _PRODUCER_SINGLETON is not None:
        await _PRODUCER_SINGLETON.stop()
        _PRODUCER_SINGLETON = None


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------
_DEFAULT_AUTO_OFFSET_RESET = "earliest"
_DEFAULT_SESSION_TIMEOUT_MS = 30_000
_DEFAULT_MAX_POLL_RECORDS = 500

HandlerType = Callable[[EventEnvelope], Coroutine[Any, Any, None]]


class SCVRIConsumer:
    """Async Kafka consumer that deserialises EventEnvelopes or yields records directly.

    Supports two usage modes:
    1. Managed callback mode:
       consumer = SCVRIConsumer(topics=[...], group_id=..., handler=my_handler)
       await consumer.start()

    2. Async iterator / context manager mode:
       consumer = SCVRIConsumer(topics=[...], group_id=...)
       async with consumer:
           async for message in consumer:
               process(message)
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        handler: HandlerType | None = None,
        dlq_enabled: bool = True,
        max_poll_records: int = _DEFAULT_MAX_POLL_RECORDS,
        bootstrap_servers: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._topics = topics
        self._group_id = group_id
        self._handler = handler
        self._dlq_enabled = dlq_enabled
        self._max_poll_records = max_poll_records
        self._bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self._extra_kwargs = kwargs
        self._stop_event = asyncio.Event()
        self._consumer: Any = None
        self._producer: SCVRIProducer | None = None
        self._started = False

    def _build_consumer(self) -> Any:
        from aiokafka import AIOKafkaConsumer  # noqa: PLC0415

        def _safe_json_deserializer(v: bytes | None) -> Any:
            if v is None:
                return None
            try:
                return json.loads(v.decode("utf-8"))
            except Exception:
                return v

        return AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset=_DEFAULT_AUTO_OFFSET_RESET,
            enable_auto_commit=False,
            session_timeout_ms=_DEFAULT_SESSION_TIMEOUT_MS,
            max_poll_records=self._max_poll_records,
            value_deserializer=_safe_json_deserializer,
            **_sasl_kwargs(),
        )

    async def _ensure_started(self) -> None:
        if not self._started:
            if self._consumer is None:
                self._consumer = self._build_consumer()
            await self._consumer.start()
            self._started = True
            log.info(
                "kafka.consumer.started",
                topics=self._topics,
                group_id=self._group_id,
            )

    async def __aenter__(self) -> "SCVRIConsumer":
        await self._ensure_started()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    def __aiter__(self) -> "SCVRIConsumer":
        return self

    async def __anext__(self) -> Any:
        if self._stop_event.is_set():
            raise StopAsyncIteration
        await self._ensure_started()
        try:
            msg = await self._consumer.__anext__()
            return msg
        except StopAsyncIteration:
            raise
        except Exception as exc:
            if self._stop_event.is_set():
                raise StopAsyncIteration
            raise exc

    async def commit(self) -> None:
        """Commit offsets manually."""
        if self._consumer and self._started:
            await self._consumer.commit()

    async def start(self) -> None:
        """Start consuming messages — runs until ``stop()`` is called if handler is provided."""
        await self._ensure_started()

        if self._dlq_enabled and self._handler:
            self._producer = SCVRIProducer()
            await self._producer.start()

        try:
            if self._handler:
                async for msg in self._consumer:
                    if self._stop_event.is_set():
                        break
                    await self._process_message(msg, self._producer)
                    await self._consumer.commit()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Signal consumer to stop and close underlying connections."""
        self._stop_event.set()
        if self._consumer and self._started:
            try:
                await self._consumer.stop()
            except Exception as e:
                log.warning("kafka.consumer.stop_error", error=str(e))
            self._started = False
        if self._producer:
            try:
                await self._producer.stop()
            except Exception as e:
                log.warning("kafka.producer.stop_error", error=str(e))
            self._producer = None
        log.info("kafka.consumer.stopped", group_id=self._group_id)

    async def _process_message(self, msg: Any, producer: SCVRIProducer | None) -> None:
        try:
            if isinstance(msg.value, dict):
                envelope = EventEnvelope(**msg.value)
            elif isinstance(msg.value, (bytes, bytearray)):
                envelope = EventEnvelope.from_json(msg.value)
            else:
                envelope = EventEnvelope.from_json(str(msg.value).encode("utf-8"))

            log.debug(
                "kafka.message.received",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                event_type=envelope.event_type,
                event_id=envelope.event_id,
            )
            if self._handler:
                await self._handler(envelope)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "kafka.handler_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=str(exc),
            )
            if producer and self._dlq_enabled:
                try:
                    dlq_topic = f"{msg.topic}.dlq"
                    raw_val = json.dumps(msg.value) if isinstance(msg.value, dict) else (msg.value.decode("utf-8") if isinstance(msg.value, (bytes, bytearray)) else str(msg.value))
                    await producer.publish(
                        topic=dlq_topic,
                        key=msg.key.decode("utf-8") if isinstance(msg.key, (bytes, bytearray)) else str(msg.key or "unknown"),
                        value={
                            "original_raw": raw_val,
                            "error": str(exc),
                            "topic": msg.topic,
                            "partition": msg.partition,
                            "offset": msg.offset,
                        },
                        event_type="dlq.handler_error",
                        retries=1,
                    )
                except Exception as dlq_exc:  # noqa: BLE001
                    log.critical("kafka.dlq_write_failed", error=str(dlq_exc))
