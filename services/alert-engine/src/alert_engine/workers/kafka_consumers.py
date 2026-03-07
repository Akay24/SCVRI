"""Kafka consumers — evaluate alert rules against incoming events."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from scvri_shared.kafka import SCVRIConsumer
from scvri_shared.logging import get_logger
from scvri_shared.config import settings

log = get_logger(__name__)

# Topics to consume
TOPICS = ["risk.events", "visibility.events", "scorecard.computed"]

# System service account used as the user_id when rules fire automatically
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def handle_event(event: dict[str, Any]) -> None:
    """Process a single incoming Kafka event through the rule engine."""
    from alert_engine.services import rule_service  # noqa: PLC0415 — avoid circular import at module load
    from scvri_shared.database import get_tenant_session  # noqa: PLC0415

    topic: str = event.get("_topic", "")
    event_type: str = event.get("event_type", "")
    tenant_id_raw: str = event.get("tenant_id", "")
    payload: dict[str, Any] = event.get("payload", event)

    if not tenant_id_raw:
        log.warning("kafka.event.missing_tenant_id", topic=topic)
        return

    try:
        tenant_id = uuid.UUID(tenant_id_raw)
    except ValueError:
        log.warning("kafka.event.invalid_tenant_id", value=tenant_id_raw)
        return

    log.debug("kafka.event.received", topic=topic, event_type=event_type, tenant_id=str(tenant_id))

    async with get_tenant_session(tenant_id) as db:
        try:
            fired = await rule_service.evaluate_event_rules(
                db,
                tenant_id=tenant_id,
                event_topic=topic,
                event_type=event_type,
                event_payload=payload,
            )
            log.info(
                "kafka.rules.evaluated",
                topic=topic,
                event_type=event_type,
                rules_fired=len(fired),
            )
        except Exception as exc:  # noqa: BLE001
            log.error("kafka.rule_evaluation.failed", error=str(exc))


async def run_consumers() -> None:
    """Start Kafka consumers for all SCVRI event topics."""
    consumer = SCVRIConsumer(
        topics=TOPICS,
        group_id="alert-engine-rules",
        bootstrap_servers=settings.kafka_bootstrap_servers,
    )

    log.info("kafka.consumers.starting", topics=TOPICS)

    async for raw_msg in consumer:
        try:
            value = raw_msg.value
            if isinstance(value, (bytes, bytearray)):
                value = json.loads(value)

            # Inject the topic so handle_event can route correctly
            value["_topic"] = raw_msg.topic

            await handle_event(value)

        except json.JSONDecodeError as exc:
            log.warning("kafka.message.decode_failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.error("kafka.message.processing_failed", error=str(exc))


def start_consumers_background() -> asyncio.Task:
    """Schedule the Kafka consumer loop as a background asyncio task."""
    loop = asyncio.get_event_loop()
    task = loop.create_task(run_consumers())
    task.add_done_callback(
        lambda t: log.error("kafka.consumers.stopped", exc=str(t.exception())) if t.exception() else None
    )
    return task
