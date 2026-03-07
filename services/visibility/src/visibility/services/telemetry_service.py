"""IoT telemetry service — ingest, geofence evaluation, device management."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError
from scvri_shared.kafka import get_producer
from scvri_shared.logging import get_logger
from visibility.schemas.telemetry import (
    DeviceCreate,
    DeviceResponse,
    GeofenceCreate,
    GeofenceResponse,
    TelemetryEventResponse,
    TelemetryPayload,
    TelemetryQueryParams,
)

log = get_logger(__name__)

# Alert thresholds (configurable per tenant in future)
_TEMPERATURE_BREACH_HIGH_C = 30.0
_TEMPERATURE_BREACH_LOW_C = -5.0
_HUMIDITY_BREACH_HIGH_PCT = 85.0
_SHOCK_BREACH_G = 5.0


# ── Telemetry ingest ──────────────────────────────────────────────────────────

async def process_telemetry(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payload: TelemetryPayload,
) -> TelemetryEventResponse:
    """Persist a telemetry event and check alert conditions."""

    alert_triggered = False

    # Alert checks
    if payload.event_type == "temperature_breach" or (
        payload.temperature_c is not None
        and not (_TEMPERATURE_BREACH_LOW_C <= payload.temperature_c <= _TEMPERATURE_BREACH_HIGH_C)
    ):
        alert_triggered = True
        await _emit_telemetry_alert(payload, tenant_id, "temperature_breach")

    if payload.event_type == "humidity_breach" or (
        payload.humidity_pct is not None and payload.humidity_pct > _HUMIDITY_BREACH_HIGH_PCT
    ):
        alert_triggered = True
        await _emit_telemetry_alert(payload, tenant_id, "humidity_breach")

    if payload.event_type == "shock_detected" or (
        payload.shock_g is not None and payload.shock_g > _SHOCK_BREACH_G
    ):
        alert_triggered = True
        await _emit_telemetry_alert(payload, tenant_id, "shock_detected")

    # Geofence evaluation (only if GPS present)
    geofence_id = payload.geofence_id
    geofence_name = payload.geofence_name
    if payload.latitude is not None and payload.longitude is not None:
        geofence_id, geofence_name = await _evaluate_geofence(
            db, tenant_id, payload, geofence_id, geofence_name
        )

    event_id = uuid.uuid4()
    processed_at = datetime.now(timezone.utc)

    await db.execute(text("""
        INSERT INTO visibility.telemetry_events
            (id, device_id, shipment_id, tenant_id, event_type,
             latitude, longitude, temperature_c, humidity_pct, shock_g,
             battery_pct, geofence_id, geofence_name,
             occurred_at, processed_at, alert_triggered)
        VALUES
            (:id, :device_id, :shipment_id, :tenant_id, :event_type,
             :lat, :lon, :temp, :humidity, :shock,
             :battery, :geofence_id, :geofence_name,
             :occurred_at, :processed_at, :alert_triggered)
        ON CONFLICT DO NOTHING
    """), {
        "id": str(event_id),
        "device_id": payload.device_id,
        "shipment_id": str(payload.shipment_id) if payload.shipment_id else None,
        "tenant_id": str(tenant_id),
        "event_type": payload.event_type,
        "lat": payload.latitude,
        "lon": payload.longitude,
        "temp": payload.temperature_c,
        "humidity": payload.humidity_pct,
        "shock": payload.shock_g,
        "battery": payload.battery_pct,
        "geofence_id": str(geofence_id) if geofence_id else None,
        "geofence_name": geofence_name,
        "occurred_at": payload.occurred_at,
        "processed_at": processed_at,
        "alert_triggered": alert_triggered,
    })

    # Update device last_seen / battery
    await db.execute(text("""
        UPDATE visibility.devices
        SET last_seen_at  = :now,
            battery_pct  = COALESCE(:battery, battery_pct),
            shipment_id  = COALESCE(:shipment_id, shipment_id),
            updated_at   = :now
        WHERE device_id = :device_id AND tenant_id = :tenant_id
    """), {
        "now": processed_at,
        "battery": payload.battery_pct,
        "shipment_id": str(payload.shipment_id) if payload.shipment_id else None,
        "device_id": payload.device_id,
        "tenant_id": str(tenant_id),
    })

    # Update shipment current location if GPS
    if payload.latitude is not None and payload.shipment_id is not None:
        await db.execute(text("""
            UPDATE visibility.shipments
            SET current_lat  = :lat,
                current_lon  = :lon,
                updated_at   = now()
            WHERE id = :shipment_id AND tenant_id = :tenant_id
        """), {
            "lat": payload.latitude,
            "lon": payload.longitude,
            "shipment_id": str(payload.shipment_id),
            "tenant_id": str(tenant_id),
        })

    await db.commit()

    log.info(
        "telemetry.processed",
        event_id=str(event_id),
        device_id=payload.device_id,
        event_type=payload.event_type,
        alert_triggered=alert_triggered,
    )

    return TelemetryEventResponse(
        id=event_id,
        device_id=payload.device_id,
        shipment_id=payload.shipment_id,
        tenant_id=tenant_id,
        event_type=payload.event_type,
        latitude=payload.latitude,
        longitude=payload.longitude,
        temperature_c=payload.temperature_c,
        humidity_pct=payload.humidity_pct,
        shock_g=payload.shock_g,
        battery_pct=payload.battery_pct,
        geofence_id=geofence_id,
        geofence_name=geofence_name,
        occurred_at=payload.occurred_at,
        processed_at=processed_at,
        alert_triggered=alert_triggered,
    )


async def _emit_telemetry_alert(
    payload: TelemetryPayload,
    tenant_id: uuid.UUID,
    alert_type: str,
) -> None:
    async with get_producer() as producer:
        await producer.send(
            topic="visibility.events",
            event_type=f"telemetry.{alert_type}",
            payload={
                "device_id": payload.device_id,
                "shipment_id": str(payload.shipment_id) if payload.shipment_id else None,
                "alert_type": alert_type,
                "value": {
                    "temperature_c": payload.temperature_c,
                    "humidity_pct": payload.humidity_pct,
                    "shock_g": payload.shock_g,
                },
                "location": {
                    "lat": payload.latitude,
                    "lon": payload.longitude,
                },
                "occurred_at": payload.occurred_at.isoformat(),
            },
            tenant_id=str(tenant_id),
        )


async def _evaluate_geofence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payload: TelemetryPayload,
    previous_geofence_id: uuid.UUID | None,
    previous_geofence_name: str | None,
) -> tuple[uuid.UUID | None, str | None]:
    """Check if lat/lon falls inside any active geofence."""
    fences = (await db.execute(text("""
        SELECT id, name, min_lat, max_lat, min_lon, max_lon, wkt_polygon
        FROM visibility.geofences
        WHERE tenant_id = :tenant_id AND is_active = TRUE
    """), {"tenant_id": str(tenant_id)})).mappings().all()

    lat, lon = payload.latitude, payload.longitude

    for fence in fences:
        inside = False

        if fence["wkt_polygon"]:
            try:
                from shapely import wkt  # noqa: PLC0415
                from shapely.geometry import Point  # noqa: PLC0415
                poly = wkt.loads(fence["wkt_polygon"])
                inside = poly.contains(Point(lon, lat))
            except Exception:  # noqa: BLE001
                pass
        elif all(fence.get(k) is not None for k in ["min_lat", "max_lat", "min_lon", "max_lon"]):
            inside = (
                fence["min_lat"] <= lat <= fence["max_lat"]
                and fence["min_lon"] <= lon <= fence["max_lon"]
            )

        if inside:
            fence_id = uuid.UUID(str(fence["id"]))
            if previous_geofence_id != fence_id:
                # Geofence transition — emit Kafka event
                async with get_producer() as producer:
                    await producer.send(
                        topic="visibility.events",
                        event_type="telemetry.geofence_enter",
                        payload={
                            "device_id": payload.device_id,
                            "shipment_id": str(payload.shipment_id) if payload.shipment_id else None,
                            "geofence_id": str(fence_id),
                            "geofence_name": fence["name"],
                            "latitude": lat,
                            "longitude": lon,
                        },
                        tenant_id=str(tenant_id),
                    )
            return fence_id, fence["name"]

    # Not in any fence — did we just leave one?
    if previous_geofence_id is not None:
        async with get_producer() as producer:
            await producer.send(
                topic="visibility.events",
                event_type="telemetry.geofence_exit",
                payload={
                    "device_id": payload.device_id,
                    "shipment_id": str(payload.shipment_id) if payload.shipment_id else None,
                    "geofence_id": str(previous_geofence_id),
                    "geofence_name": previous_geofence_name,
                    "latitude": lat,
                    "longitude": lon,
                },
                tenant_id=str(tenant_id),
            )

    return None, None


# ── Query ─────────────────────────────────────────────────────────────────────

async def query_telemetry(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    params: TelemetryQueryParams,
) -> list[TelemetryEventResponse]:
    filters = "tenant_id = :tenant_id"
    p: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": params.limit}

    if params.shipment_id:
        filters += " AND shipment_id = :shipment_id"
        p["shipment_id"] = str(params.shipment_id)
    if params.device_id:
        filters += " AND device_id = :device_id"
        p["device_id"] = params.device_id
    if params.event_type:
        filters += " AND event_type = :event_type"
        p["event_type"] = params.event_type
    if params.from_dt:
        filters += " AND occurred_at >= :from_dt"
        p["from_dt"] = params.from_dt
    if params.to_dt:
        filters += " AND occurred_at <= :to_dt"
        p["to_dt"] = params.to_dt

    rows = (await db.execute(text(f"""
        SELECT * FROM visibility.telemetry_events
        WHERE {filters}
        ORDER BY occurred_at DESC
        LIMIT :limit
    """), p)).mappings().all()

    return [_map_telemetry_event(r) for r in rows]


def _map_telemetry_event(row: Any) -> TelemetryEventResponse:
    return TelemetryEventResponse(
        id=row["id"],
        device_id=row["device_id"],
        shipment_id=row.get("shipment_id"),
        tenant_id=row["tenant_id"],
        event_type=row["event_type"],
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        temperature_c=row.get("temperature_c"),
        humidity_pct=row.get("humidity_pct"),
        shock_g=row.get("shock_g"),
        battery_pct=row.get("battery_pct"),
        geofence_id=row.get("geofence_id"),
        geofence_name=row.get("geofence_name"),
        occurred_at=row["occurred_at"],
        processed_at=row["processed_at"],
        alert_triggered=bool(row.get("alert_triggered", False)),
    )


# ── Geofences ─────────────────────────────────────────────────────────────────

async def create_geofence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: GeofenceCreate,
) -> GeofenceResponse:
    geo_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO visibility.geofences
            (id, tenant_id, name, description, wkt_polygon,
             min_lat, max_lat, min_lon, max_lon, is_active, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :name, :description, :wkt,
             :min_lat, :max_lat, :min_lon, :max_lon, TRUE, now(), now())
    """), {
        "id": str(geo_id),
        "tenant_id": str(tenant_id),
        "name": data.name,
        "description": data.description,
        "wkt": data.wkt_polygon,
        "min_lat": data.min_lat,
        "max_lat": data.max_lat,
        "min_lon": data.min_lon,
        "max_lon": data.max_lon,
    })
    await db.commit()
    return await get_geofence(db, tenant_id, geo_id)


async def get_geofence(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    geo_id: uuid.UUID,
) -> GeofenceResponse:
    row = (await db.execute(text("""
        SELECT * FROM visibility.geofences WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(geo_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()
    if row is None:
        raise NotFoundError(f"Geofence {geo_id} not found")
    return _map_geofence(row)


async def list_geofences(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[GeofenceResponse]:
    rows = (await db.execute(text("""
        SELECT * FROM visibility.geofences
        WHERE tenant_id = :tenant_id AND is_active = TRUE
        ORDER BY name
    """), {"tenant_id": str(tenant_id)})).mappings().all()
    return [_map_geofence(r) for r in rows]


def _map_geofence(row: Any) -> GeofenceResponse:
    return GeofenceResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        description=row.get("description"),
        wkt_polygon=row.get("wkt_polygon"),
        min_lat=row.get("min_lat"),
        max_lat=row.get("max_lat"),
        min_lon=row.get("min_lon"),
        max_lon=row.get("max_lon"),
        is_active=bool(row.get("is_active", True)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Devices ───────────────────────────────────────────────────────────────────

async def register_device(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: DeviceCreate,
) -> DeviceResponse:
    device_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO visibility.devices
            (id, tenant_id, device_id, device_type, shipment_id,
             serial_number, firmware_version, is_active, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :device_id, :device_type, :shipment_id,
             :serial_number, :firmware_version, TRUE, now(), now())
        ON CONFLICT (tenant_id, device_id) DO UPDATE
        SET device_type     = EXCLUDED.device_type,
            shipment_id     = COALESCE(EXCLUDED.shipment_id, devices.shipment_id),
            firmware_version= COALESCE(EXCLUDED.firmware_version, devices.firmware_version),
            updated_at      = now()
    """), {
        "id": str(device_id),
        "tenant_id": str(tenant_id),
        "device_id": data.device_id,
        "device_type": data.device_type,
        "shipment_id": str(data.shipment_id) if data.shipment_id else None,
        "serial_number": data.serial_number,
        "firmware_version": data.firmware_version,
    })
    await db.commit()

    row = (await db.execute(text("""
        SELECT * FROM visibility.devices
        WHERE device_id = :device_id AND tenant_id = :tenant_id
    """), {"device_id": data.device_id, "tenant_id": str(tenant_id)})).mappings().one()

    return DeviceResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        device_id=row["device_id"],
        device_type=row["device_type"],
        shipment_id=row.get("shipment_id"),
        serial_number=row.get("serial_number"),
        firmware_version=row.get("firmware_version"),
        last_seen_at=row.get("last_seen_at"),
        battery_pct=row.get("battery_pct"),
        is_active=bool(row.get("is_active", True)),
        created_at=row["created_at"],
    )
