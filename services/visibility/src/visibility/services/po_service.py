"""Purchase Order service — CRUD + state machine transitions."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError, BusinessRuleError
from scvri_shared.kafka import get_producer
from scvri_shared.outbox_relay import schedule_outbox_event
from scvri_shared.logging import get_logger
from visibility.schemas.purchase_order import (
    PO_TRANSITIONS,
    TERMINAL_PO_STATUSES,
    POEventRequest,
    POLineShipment,
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    PODeliveryMetrics,
)

log = get_logger(__name__)


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_purchase_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: PurchaseOrderCreate,
) -> PurchaseOrderResponse:
    po_id = uuid.uuid4()
    total_value = sum(line.quantity_ordered * line.unit_price for line in data.lines)

    await db.execute(text("""
        INSERT INTO visibility.purchase_orders
            (id, tenant_id, supplier_id, po_number, status, currency,
             total_value, requested_delivery_date, shipping_address, notes,
             created_by, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :supplier_id, :po_number, 'draft', :currency,
             :total_value, :requested_delivery_date, :shipping_address, :notes,
             :created_by, now(), now())
    """), {
        "id": str(po_id),
        "tenant_id": str(tenant_id),
        "supplier_id": str(data.supplier_id),
        "po_number": data.po_number,
        "currency": data.currency,
        "total_value": total_value,
        "requested_delivery_date": data.requested_delivery_date,
        "shipping_address": data.shipping_address,
        "notes": data.notes,
        "created_by": str(user_id),
    })

    for line in data.lines:
        await db.execute(text("""
            INSERT INTO visibility.po_lines
                (id, po_id, tenant_id, line_number, product_code, product_description,
                 quantity_ordered, quantity_shipped, quantity_received,
                 unit_of_measure, unit_price, currency, status,
                 requested_delivery_date, created_at, updated_at)
            VALUES
                (:id, :po_id, :tenant_id, :line_number, :product_code, :description,
                 :qty_ordered, 0, 0, :uom, :unit_price, :currency, 'open',
                 :delivery_date, now(), now())
        """), {
            "id": str(uuid.uuid4()),
            "po_id": str(po_id),
            "tenant_id": str(tenant_id),
            "line_number": line.line_number,
            "product_code": line.product_code,
            "description": line.product_description,
            "qty_ordered": line.quantity_ordered,
            "uom": line.unit_of_measure,
            "unit_price": line.unit_price,
            "currency": line.currency,
            "delivery_date": line.requested_delivery_date,
        })

    await db.commit()

    log.info(
        "po.created",
        po_id=str(po_id),
        supplier_id=str(data.supplier_id),
        po_number=data.po_number,
    )

    return await get_purchase_order(db, tenant_id, po_id)


async def get_purchase_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    po_id: uuid.UUID,
) -> PurchaseOrderResponse:
    row = (await db.execute(text("""
        SELECT * FROM visibility.purchase_orders
        WHERE id = :po_id AND tenant_id = :tenant_id
    """), {"po_id": str(po_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    lines = (await db.execute(text("""
        SELECT * FROM visibility.po_lines
        WHERE po_id = :po_id
        ORDER BY line_number
    """), {"po_id": str(po_id)})).mappings().all()

    return _map_po_response(row, lines)


async def list_purchase_orders(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PurchaseOrderResponse]:
    filters = "tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": limit, "offset": offset}
    if supplier_id:
        filters += " AND supplier_id = :supplier_id"
        params["supplier_id"] = str(supplier_id)
    if status:
        filters += " AND status = :status"
        params["status"] = status

    rows = (await db.execute(text(f"""
        SELECT * FROM visibility.purchase_orders
        WHERE {filters}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    result = []
    for row in rows:
        lines = (await db.execute(text("""
            SELECT * FROM visibility.po_lines WHERE po_id = :po_id ORDER BY line_number
        """), {"po_id": str(row["id"])})).mappings().all()
        result.append(_map_po_response(row, lines))
    return result


async def update_purchase_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    po_id: uuid.UUID,
    data: PurchaseOrderUpdate,
) -> PurchaseOrderResponse:
    po = await get_purchase_order(db, tenant_id, po_id)
    if po.status in TERMINAL_PO_STATUSES:
        raise BusinessRuleError(f"PO {po_id} is in terminal state '{po.status}' and cannot be updated")

    await db.execute(text("""
        UPDATE visibility.purchase_orders
        SET requested_delivery_date = COALESCE(:req_delivery, requested_delivery_date),
            shipping_address = COALESCE(:shipping_address, shipping_address),
            notes = COALESCE(:notes, notes),
            updated_at = now()
        WHERE id = :po_id AND tenant_id = :tenant_id
    """), {
        "req_delivery": data.requested_delivery_date,
        "shipping_address": data.shipping_address,
        "notes": data.notes,
        "po_id": str(po_id),
        "tenant_id": str(tenant_id),
    })
    await db.commit()
    return await get_purchase_order(db, tenant_id, po_id)


# ── State machine ─────────────────────────────────────────────────────────────

async def apply_po_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    po_id: uuid.UUID,
    event: POEventRequest,
) -> PurchaseOrderResponse:
    po = await get_purchase_order(db, tenant_id, po_id)
    current = po.status

    transition_key = (current, event.event)
    next_status = PO_TRANSITIONS.get(transition_key)
    if next_status is None:
        raise BusinessRuleError(
            f"Event '{event.event}' is not valid for PO in status '{current}'"
        )

    timestamp_updates = _timestamp_columns(event.event)

    await db.execute(text(f"""
        UPDATE visibility.purchase_orders
        SET status = :next_status,
            {timestamp_updates}
            updated_at = now()
        WHERE id = :po_id AND tenant_id = :tenant_id
    """), {"next_status": next_status, "po_id": str(po_id), "tenant_id": str(tenant_id)})

    # Apply line-level quantity updates if provided
    if event.line_updates:
        await _apply_line_updates(db, po_id, event.event, event.line_updates)

    # Schedule Outbox event for zero-loss reliable delivery
    await schedule_outbox_event(
        db,
        tenant_id=tenant_id,
        topic="visibility.events",
        event_type="po.status.changed",
        payload={
            "po_id": str(po_id),
            "supplier_id": str(po.supplier_id),
            "previous_status": current,
            "new_status": next_status,
            "event": event.event,
            "notes": event.notes,
            "changed_by": str(user_id),
        },
        event_key=str(po_id),
    )

    await db.commit()

    updated_po = await get_purchase_order(db, tenant_id, po_id)

    # Publish Kafka event opportunistically
    try:
        async with get_producer() as producer:
            await producer.send(
                topic="visibility.events",
                event_type="po.status.changed",
                payload={
                    "po_id": str(po_id),
                    "supplier_id": str(po.supplier_id),
                    "previous_status": current,
                    "new_status": next_status,
                    "event": event.event,
                    "notes": event.notes,
                    "changed_by": str(user_id),
                },
                tenant_id=str(tenant_id),
            )
    except Exception as exc:
        log.warning("po_event_direct_publish_failed_relaying_via_outbox", error=str(exc))

    log.info(
        "po.event.applied",
        po_id=str(po_id),
        po_event=event.event,
        from_status=current,
        to_status=next_status,
    )
    return updated_po



def _timestamp_columns(event: str) -> str:
    """Return SET clauses that stamp the relevant event timestamp."""
    mapping = {
        "confirm":          "confirmed_at = now(),",
        "ship_partial":     "first_shipped_at = COALESCE(first_shipped_at, now()),",
        "ship_complete":    "first_shipped_at = COALESCE(first_shipped_at, now()), fully_shipped_at = now(),",
        "receive_partial":  "first_received_at = COALESCE(first_received_at, now()),",
        "receive_complete": "first_received_at = COALESCE(first_received_at, now()), fully_received_at = now(),",
        "cancel":           "cancelled_at = now(),",
    }
    return mapping.get(event, "")


async def _apply_line_updates(
    db: AsyncSession,
    po_id: uuid.UUID,
    event: str,
    updates: list[POLineShipment],
) -> None:
    col = "quantity_shipped" if event.startswith("ship") else "quantity_received"
    for upd in updates:
        await db.execute(text(f"""
            UPDATE visibility.po_lines
            SET {col} = {col} + :qty, updated_at = now()
            WHERE id = :line_id AND po_id = :po_id
        """), {"qty": upd.quantity, "line_id": str(upd.line_id), "po_id": str(po_id)})


# ── Delivery metrics ──────────────────────────────────────────────────────────

async def get_delivery_metrics(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
) -> PODeliveryMetrics:
    row = (await db.execute(text("""
        WITH po_stats AS (
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE fully_received_at IS NOT NULL
                      AND fully_received_at <= requested_delivery_date
                ) AS on_time,
                COUNT(*) FILTER (
                    WHERE fully_received_at IS NOT NULL
                      AND fully_received_at > requested_delivery_date
                ) AS late,
                AVG(
                    EXTRACT(EPOCH FROM (fully_received_at - requested_delivery_date)) / 86400
                ) FILTER (
                    WHERE fully_received_at > requested_delivery_date
                ) AS avg_days_late,
                AVG(
                    EXTRACT(EPOCH FROM (fully_received_at - confirmed_at)) / 86400
                ) FILTER (WHERE fully_received_at IS NOT NULL) AS avg_lead_time
            FROM visibility.purchase_orders
            WHERE tenant_id = :tenant_id
              AND supplier_id = :supplier_id
              AND created_at BETWEEN :period_start AND :period_end
        )
        SELECT * FROM po_stats
    """), {
        "tenant_id": str(tenant_id),
        "supplier_id": str(supplier_id),
        "period_start": period_start,
        "period_end": period_end,
    })).mappings().one()

    total = row["total"] or 0
    on_time = row["on_time"] or 0
    late = row["late"] or 0
    otd = round((on_time / total * 100), 2) if total else 0.0

    return PODeliveryMetrics(
        supplier_id=supplier_id,
        period_start=period_start,
        period_end=period_end,
        total_pos=total,
        on_time_count=on_time,
        late_count=late,
        otd_rate=otd,
        avg_days_late=float(row["avg_days_late"] or 0),
        avg_lead_time_days=float(row["avg_lead_time"] or 0),
    )


# ── Mapper ────────────────────────────────────────────────────────────────────

def _map_po_response(row: Any, lines: list[Any]) -> PurchaseOrderResponse:
    from visibility.schemas.purchase_order import POLineResponse  # noqa: PLC0415

    line_responses = [
        POLineResponse(
            id=l["id"],
            po_id=l["po_id"],
            line_number=l["line_number"],
            product_code=l["product_code"],
            product_description=l["product_description"],
            quantity_ordered=l["quantity_ordered"],
            quantity_shipped=l["quantity_shipped"],
            quantity_received=l["quantity_received"],
            unit_of_measure=l["unit_of_measure"],
            unit_price=l["unit_price"],
            currency=l["currency"],
            status=l["status"],
            requested_delivery_date=l.get("requested_delivery_date"),
            created_at=l["created_at"],
            updated_at=l["updated_at"],
        )
        for l in lines
    ]

    return PurchaseOrderResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        supplier_id=row["supplier_id"],
        po_number=row["po_number"],
        status=row["status"],
        currency=row["currency"],
        total_value=float(row["total_value"]),
        requested_delivery_date=row.get("requested_delivery_date"),
        confirmed_at=row.get("confirmed_at"),
        first_shipped_at=row.get("first_shipped_at"),
        fully_shipped_at=row.get("fully_shipped_at"),
        first_received_at=row.get("first_received_at"),
        fully_received_at=row.get("fully_received_at"),
        cancelled_at=row.get("cancelled_at"),
        shipping_address=row.get("shipping_address"),
        notes=row.get("notes"),
        lines=line_responses,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
