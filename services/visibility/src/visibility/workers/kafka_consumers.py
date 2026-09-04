"""Kafka consumers for the Visibility service.

Consumers run as long-lived asyncio tasks launched from main.py lifespan.

Topics consumed:
  - ``iot.telemetry``      → process_telemetry() for each message
  - ``erp.purchase_orders`` → upsert PO data from ERP system
  - ``supplier.events``    → react to supplier status changes
"""
from __future__ import annotations

import asyncio
import uuid

from scvri_shared.kafka import SCVRIConsumer
from scvri_shared.logging import get_logger

log = get_logger(__name__)


# ── IoT Telemetry consumer ─────────────────────────────────────────────────────

async def consume_iot_telemetry() -> None:
    """Consume messages from ``iot.telemetry``, persist + check alerts."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from scvri_shared.config import settings  # noqa: PLC0415
    from visibility.services import telemetry_service  # noqa: PLC0415
    from visibility.schemas.telemetry import TelemetryPayload  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    consumer = SCVRIConsumer(
        topics=["iot.telemetry"],
        group_id="visibility-iot-consumer",
    )

    log.info("kafka.consumer.iot.started")

    async with consumer:
        async for message in consumer:
            payload_data = message.value.get("payload", {})
            if not payload_data:
                continue

            try:
                payload = TelemetryPayload(**payload_data)
                tenant_id = payload.tenant_id or uuid.UUID(message.value.get("tenant_id", ""))

                async with async_session() as db:
                    await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})
                    await telemetry_service.process_telemetry(db, tenant_id, payload)

            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "kafka.consumer.iot.error",
                    error=str(exc),
                    partition=message.partition,
                    offset=message.offset,
                )


# ── ERP Purchase Order consumer ───────────────────────────────────────────────

async def consume_erp_purchase_orders() -> None:
    """Consume PO lifecycle events from the ERP integration layer.

    ERP events carry a canonical ``PurchaseOrderCreate``-compatible payload.
    The service upserts the PO using ``po_number`` as idempotency key.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from scvri_shared.config import settings  # noqa: PLC0415
    from visibility.services import po_service  # noqa: PLC0415
    from visibility.schemas.purchase_order import PurchaseOrderCreate  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    consumer = SCVRIConsumer(
        topics=["erp.purchase_orders"],
        group_id="visibility-erp-po-consumer",
    )

    log.info("kafka.consumer.erp_po.started")

    async with consumer:
        async for message in consumer:
            event_type = message.value.get("event_type", "")
            tenant_id_str = message.value.get("tenant_id", "")
            payload_data = message.value.get("payload", {})

            if not tenant_id_str or not payload_data:
                continue

            try:
                tenant_id = uuid.UUID(tenant_id_str)
                system_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")  # ERP service account

                if event_type == "erp.po.created":
                    po_in = PurchaseOrderCreate(**payload_data)
                    async with async_session() as db:
                        await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})
                        # Idempotency: skip if po_number already exists
                        exists = (await db.execute(text("""
                            SELECT 1 FROM visibility.purchase_orders
                            WHERE tenant_id = :t AND po_number = :po_num
                        """), {"t": str(tenant_id), "po_num": po_in.po_number})).scalar()
                        if not exists:
                            await po_service.create_purchase_order(db, tenant_id, system_user_id, po_in)

                elif event_type == "erp.po.status_changed":
                    # ERP confirms PO
                    from visibility.schemas.purchase_order import POEventRequest  # noqa: PLC0415
                    po_id = uuid.UUID(payload_data["po_id"])
                    event = payload_data.get("event", "confirm")
                    async with async_session() as db:
                        await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})
                        await po_service.apply_po_event(
                            db, tenant_id, system_user_id, po_id,
                            POEventRequest(event=event, notes="Applied from ERP event"),
                        )

            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "kafka.consumer.erp_po.error",
                    error=str(exc),
                    event_type=event_type,
                    partition=message.partition,
                    offset=message.offset,
                )


# ── Supplier events consumer ──────────────────────────────────────────────────

async def consume_supplier_events() -> None:
    """React to supplier status changes (e.g. deactivated supplier → flag open POs)."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from scvri_shared.config import settings  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    consumer = SCVRIConsumer(
        topics=["supplier.events"],
        group_id="visibility-supplier-events-consumer",
    )

    log.info("kafka.consumer.supplier_events.started")

    async with consumer:
        async for message in consumer:
            event_type = message.value.get("event_type", "")
            tenant_id_str = message.value.get("tenant_id", "")
            payload_data = message.value.get("payload", {})

            if event_type != "supplier.status.changed":
                continue

            new_status = payload_data.get("new_status", "")
            if new_status not in ("inactive", "suspended", "blacklisted"):
                continue

            try:
                tenant_id = uuid.UUID(tenant_id_str)
                supplier_id = uuid.UUID(payload_data["supplier_id"])

                async with async_session() as db:
                    await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})
                    # Flag all open POs with a note
                    await db.execute(text("""
                        UPDATE visibility.purchase_orders
                        SET notes = COALESCE(notes, '') || ' [WARNING: supplier status changed to ' || :status || ']',
                            updated_at = now()
                        WHERE tenant_id = :tenant_id
                          AND supplier_id = :supplier_id
                          AND status NOT IN ('received', 'cancelled')
                    """), {
                        "status": new_status,
                        "tenant_id": str(tenant_id),
                        "supplier_id": str(supplier_id),
                    })
                    await db.commit()

                log.info(
                    "supplier.event.po_flagged",
                    supplier_id=str(supplier_id),
                    new_status=new_status,
                )

            except Exception as exc:  # noqa: BLE001
                log.warning("kafka.consumer.supplier_events.error", error=str(exc))


# ── Startup helper ─────────────────────────────────────────────────────────────

async def start_all_consumers() -> list[asyncio.Task]:
    """Launch all Kafka consumer coroutines as background asyncio tasks."""
    tasks = [
        asyncio.create_task(consume_iot_telemetry(), name="kafka-iot-telemetry"),
        asyncio.create_task(consume_erp_purchase_orders(), name="kafka-erp-po"),
        asyncio.create_task(consume_supplier_events(), name="kafka-supplier-events"),
    ]
    log.info("kafka.consumers.all_started", count=len(tasks))
    return tasks
