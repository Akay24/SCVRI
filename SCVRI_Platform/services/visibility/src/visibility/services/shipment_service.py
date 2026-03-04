"""Shipment tracking service."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError, BusinessRuleError
from scvri_shared.kafka import get_producer
from scvri_shared.logging import get_logger
from visibility.schemas.shipment import (
    ETAPredictionResponse,
    GeoCoordinate,
    ShipmentCreate,
    ShipmentKPIResponse,
    ShipmentResponse,
    ShipmentUpdate,
    TrackingEventCreate,
    TrackingEventResponse,
)

log = get_logger(__name__)

# Status severity for transition validation
_STATUS_ORDER = {
    "pending": 0,
    "picked_up": 1,
    "in_transit": 2,
    "out_for_delivery": 3,
    "customs_hold": 2,
    "exception": 2,
    "delivered": 10,
    "returned": 10,
}


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_shipment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ShipmentCreate,
) -> ShipmentResponse:
    shipment_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO visibility.shipments
            (id, tenant_id, po_id, carrier, carrier_type, tracking_number,
             status, origin_address, destination_address,
             origin_lat, origin_lon, destination_lat, destination_lon,
             estimated_arrival, weight_kg, volume_m3, incoterm, notes,
             created_by, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :po_id, :carrier, :carrier_type, :tracking_number,
             'pending', :origin_address, :destination_address,
             :origin_lat, :origin_lon, :dest_lat, :dest_lon,
             :estimated_arrival, :weight_kg, :volume_m3, :incoterm, :notes,
             :created_by, now(), now())
    """), {
        "id": str(shipment_id),
        "tenant_id": str(tenant_id),
        "po_id": str(data.po_id),
        "carrier": data.carrier,
        "carrier_type": data.carrier_type,
        "tracking_number": data.tracking_number,
        "origin_address": data.origin_address,
        "destination_address": data.destination_address,
        "origin_lat": data.origin_coords.latitude if data.origin_coords else None,
        "origin_lon": data.origin_coords.longitude if data.origin_coords else None,
        "dest_lat": data.destination_coords.latitude if data.destination_coords else None,
        "dest_lon": data.destination_coords.longitude if data.destination_coords else None,
        "estimated_arrival": data.estimated_arrival,
        "weight_kg": data.weight_kg,
        "volume_m3": data.volume_m3,
        "incoterm": data.incoterm,
        "notes": data.notes,
        "created_by": str(user_id),
    })

    await db.commit()
    log.info("shipment.created", shipment_id=str(shipment_id), po_id=str(data.po_id))
    return await get_shipment(db, tenant_id, shipment_id)


async def get_shipment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    shipment_id: uuid.UUID,
) -> ShipmentResponse:
    row = (await db.execute(text("""
        SELECT * FROM visibility.shipments
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(shipment_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"Shipment {shipment_id} not found")

    events = (await db.execute(text("""
        SELECT * FROM visibility.tracking_events
        WHERE shipment_id = :id
        ORDER BY occurred_at DESC
    """), {"id": str(shipment_id)})).mappings().all()

    return _map_shipment(row, events)


async def list_shipments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    po_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ShipmentResponse]:
    filters = "tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": limit, "offset": offset}
    if po_id:
        filters += " AND po_id = :po_id"
        params["po_id"] = str(po_id)
    if status:
        filters += " AND status = :status"
        params["status"] = status

    rows = (await db.execute(text(f"""
        SELECT * FROM visibility.shipments
        WHERE {filters}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    results = []
    for row in rows:
        events = (await db.execute(text("""
            SELECT * FROM visibility.tracking_events
            WHERE shipment_id = :id ORDER BY occurred_at DESC
        """), {"id": str(row["id"])})).mappings().all()
        results.append(_map_shipment(row, events))
    return results


async def update_shipment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    shipment_id: uuid.UUID,
    data: ShipmentUpdate,
) -> ShipmentResponse:
    await db.execute(text("""
        UPDATE visibility.shipments
        SET estimated_arrival = COALESCE(:eta, estimated_arrival),
            tracking_number   = COALESCE(:tracking, tracking_number),
            notes             = COALESCE(:notes, notes),
            updated_at        = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "eta": data.estimated_arrival,
        "tracking": data.tracking_number,
        "notes": data.notes,
        "id": str(shipment_id),
        "tenant_id": str(tenant_id),
    })
    await db.commit()
    return await get_shipment(db, tenant_id, shipment_id)


# ── Tracking events ───────────────────────────────────────────────────────────

async def add_tracking_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: TrackingEventCreate,
) -> TrackingEventResponse:
    event_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO visibility.tracking_events
            (id, shipment_id, tenant_id, event_type, location,
             current_lat, current_lon, carrier_reference, description,
             occurred_at, created_at)
        VALUES
            (:id, :shipment_id, :tenant_id, :event_type, :location,
             :lat, :lon, :carrier_ref, :description, :occurred_at, now())
    """), {
        "id": str(event_id),
        "shipment_id": str(data.shipment_id),
        "tenant_id": str(tenant_id),
        "event_type": data.event_type,
        "location": data.location,
        "lat": data.coords.latitude if data.coords else None,
        "lon": data.coords.longitude if data.coords else None,
        "carrier_ref": data.carrier_reference,
        "description": data.description,
        "occurred_at": data.occurred_at,
    })

    # Derive shipment status from event type
    new_status = _event_to_status(data.event_type)
    actual_arrival = data.occurred_at if data.event_type == "delivered" else None

    await db.execute(text("""
        UPDATE visibility.shipments
        SET status          = :status,
            current_lat     = COALESCE(:lat, current_lat),
            current_lon     = COALESCE(:lon, current_lon),
            current_location = COALESCE(:location, current_location),
            actual_arrival  = COALESCE(:actual_arrival, actual_arrival),
            updated_at      = now()
        WHERE id = :shipment_id AND tenant_id = :tenant_id
    """), {
        "status": new_status,
        "lat": data.coords.latitude if data.coords else None,
        "lon": data.coords.longitude if data.coords else None,
        "location": data.location,
        "actual_arrival": actual_arrival,
        "shipment_id": str(data.shipment_id),
        "tenant_id": str(tenant_id),
    })

    await db.commit()

    # Kafka
    async with get_producer() as producer:
        await producer.send(
            topic="visibility.events",
            event_type="shipment.status.updated",
            payload={
                "shipment_id": str(data.shipment_id),
                "event_type": data.event_type,
                "new_status": new_status,
                "location": data.location,
                "occurred_at": data.occurred_at.isoformat(),
            },
            tenant_id=str(tenant_id),
        )

    log.info(
        "shipment.tracking_event",
        shipment_id=str(data.shipment_id),
        event_type=data.event_type,
        new_status=new_status,
    )

    return TrackingEventResponse(
        id=event_id,
        shipment_id=data.shipment_id,
        event_type=data.event_type,
        location=data.location,
        coords=data.coords,
        carrier_reference=data.carrier_reference,
        description=data.description,
        occurred_at=data.occurred_at,
        created_at=datetime.now(timezone.utc),
    )


def _event_to_status(event_type: str) -> str:
    mapping = {
        "picked_up": "picked_up",
        "departed": "in_transit",
        "arrived": "in_transit",
        "in_transit": "in_transit",
        "customs_cleared": "in_transit",
        "customs_hold": "customs_hold",
        "out_for_delivery": "out_for_delivery",
        "delivered": "delivered",
        "exception": "exception",
        "returned": "returned",
    }
    return mapping.get(event_type, "in_transit")


# ── ETA prediction ────────────────────────────────────────────────────────────

async def predict_eta(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    shipment_id: uuid.UUID,
) -> ETAPredictionResponse:
    """Rule-based ETA prediction using historical carrier performance."""
    shipment = await get_shipment(db, tenant_id, shipment_id)

    if shipment.actual_arrival:
        return ETAPredictionResponse(
            shipment_id=shipment_id,
            current_estimated_arrival=shipment.estimated_arrival,
            predicted_arrival=shipment.actual_arrival,
            confidence_days=0.0,
            delay_risk="low",
            delay_factors=["Already delivered"],
        )

    # Avg transit days for this carrier type
    carrier_avg = (await db.execute(text("""
        SELECT AVG(
            EXTRACT(EPOCH FROM (actual_arrival - created_at)) / 86400
        ) AS avg_days
        FROM visibility.shipments
        WHERE tenant_id = :tenant_id
          AND carrier_type = :carrier_type
          AND status = 'delivered'
          AND actual_arrival IS NOT NULL
          AND created_at >= now() - interval '90 days'
    """), {
        "tenant_id": str(tenant_id),
        "carrier_type": shipment.carrier_type,
    })).scalar()

    avg_days = float(carrier_avg or 14)
    predicted = datetime.now(timezone.utc) + timedelta(days=avg_days)
    current_eta = shipment.estimated_arrival

    delay_factors: list[str] = []
    delay_risk = "low"

    if current_eta and predicted > current_eta + timedelta(days=3):
        delay_factors.append("Predicted arrival exceeds ETA by more than 3 days")
        delay_risk = "high"
    elif shipment.status in ("customs_hold", "exception"):
        delay_factors.append(f"Shipment in status '{shipment.status}'")
        delay_risk = "high"
    elif current_eta and predicted > current_eta:
        delay_factors.append("Slight delay vs ETA")
        delay_risk = "medium"

    return ETAPredictionResponse(
        shipment_id=shipment_id,
        current_estimated_arrival=current_eta,
        predicted_arrival=predicted,
        confidence_days=2.0,
        delay_risk=delay_risk,
        delay_factors=delay_factors,
    )


# ── KPI ───────────────────────────────────────────────────────────────────────

async def get_shipment_kpi(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
) -> ShipmentKPIResponse:
    row = (await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (
                WHERE status = 'delivered'
                  AND actual_arrival <= estimated_arrival
            ) AS on_time,
            COUNT(*) FILTER (
                WHERE status = 'delivered'
                  AND actual_arrival > estimated_arrival
            ) AS delayed,
            COUNT(*) FILTER (WHERE status = 'customs_hold') AS customs,
            AVG(
                EXTRACT(EPOCH FROM (actual_arrival - created_at)) / 86400
            ) FILTER (WHERE status = 'delivered') AS avg_transit
        FROM visibility.shipments s
        JOIN visibility.purchase_orders p ON s.po_id = p.id
        WHERE s.tenant_id = :tenant_id
          AND p.supplier_id = :supplier_id
          AND s.created_at BETWEEN :start AND :end
    """), {
        "tenant_id": str(tenant_id),
        "supplier_id": str(supplier_id),
        "start": period_start,
        "end": period_end,
    })).mappings().one()

    total = row["total"] or 0
    on_time = row["on_time"] or 0
    otd = round((on_time / total * 100), 2) if total else 0.0

    return ShipmentKPIResponse(
        supplier_id=supplier_id,
        period_start=period_start,
        period_end=period_end,
        total_shipments=total,
        on_time_deliveries=on_time,
        delayed_deliveries=row["delayed"] or 0,
        in_customs_hold=row["customs"] or 0,
        avg_transit_days=float(row["avg_transit"] or 0),
        otd_rate=otd,
    )


# ── Mapper ────────────────────────────────────────────────────────────────────

def _map_shipment(row: Any, events: list[Any]) -> ShipmentResponse:
    event_responses = [
        TrackingEventResponse(
            id=e["id"],
            shipment_id=e["shipment_id"],
            event_type=e["event_type"],
            location=e["location"],
            coords=GeoCoordinate(
                latitude=e["current_lat"],
                longitude=e["current_lon"],
            ) if e.get("current_lat") else None,
            carrier_reference=e.get("carrier_reference"),
            description=e.get("description"),
            occurred_at=e["occurred_at"],
            created_at=e["created_at"],
        )
        for e in events
    ]

    return ShipmentResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        po_id=row["po_id"],
        carrier=row["carrier"],
        carrier_type=row["carrier_type"],
        tracking_number=row["tracking_number"],
        status=row["status"],
        origin_address=row["origin_address"],
        destination_address=row["destination_address"],
        origin_coords=GeoCoordinate(
            latitude=row["origin_lat"], longitude=row["origin_lon"]
        ) if row.get("origin_lat") else None,
        destination_coords=GeoCoordinate(
            latitude=row["destination_lat"], longitude=row["destination_lon"]
        ) if row.get("destination_lat") else None,
        current_coords=GeoCoordinate(
            latitude=row["current_lat"], longitude=row["current_lon"]
        ) if row.get("current_lat") else None,
        current_location=row.get("current_location"),
        estimated_arrival=row.get("estimated_arrival"),
        actual_arrival=row.get("actual_arrival"),
        weight_kg=row.get("weight_kg"),
        volume_m3=row.get("volume_m3"),
        incoterm=row.get("incoterm"),
        notes=row.get("notes"),
        events=event_responses,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
