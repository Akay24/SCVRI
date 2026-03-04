"""IoT telemetry schemas (pydantic v2).

Telemetry messages arrive from IoT devices attached to shipment containers.
They are consumed from the ``iot.telemetry`` Kafka topic.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import field_validator, model_validator

from scvri_shared.schemas import CamelBase

# ── Device types ──────────────────────────────────────────────────────────────

DeviceType = Literal[
    "gps_tracker",
    "temperature_logger",
    "humidity_sensor",
    "shock_detector",
    "light_sensor",     # detect container opening
    "combo",            # multi-sensor unit
]

TelemetryEventType = Literal[
    "location_update",
    "temperature_breach",
    "humidity_breach",
    "shock_detected",
    "light_detected",    # potential tampering
    "geofence_enter",
    "geofence_exit",
    "device_heartbeat",
    "battery_low",
]


# ── Raw inbound telemetry (from Kafka) ────────────────────────────────────────

class TelemetryPayload(CamelBase):
    """Canonical shape of messages on the ``iot.telemetry`` Kafka topic."""

    device_id: str
    shipment_id: uuid.UUID | None = None   # may be null if device not yet linked
    tenant_id: uuid.UUID | None = None
    event_type: TelemetryEventType
    occurred_at: datetime

    # Location (optional — GPS devices only)
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    speed_kmh: float | None = None
    heading_deg: float | None = None

    # Environmental
    temperature_c: float | None = None
    humidity_pct: float | None = None

    # Shock
    shock_g: float | None = None            # G-force magnitude

    # Geofence (populated by platform after eval)
    geofence_id: uuid.UUID | None = None
    geofence_name: str | None = None

    # Device status
    battery_pct: int | None = None
    signal_strength_dbm: int | None = None

    # Raw from device firmware
    firmware_version: str | None = None
    raw_payload: dict | None = None         # pass-through unrecognised fields

    @field_validator("latitude")
    @classmethod
    def lat_range(cls, v: float | None) -> float | None:
        if v is not None and not (-90 <= v <= 90):
            raise ValueError("latitude out of range")
        return v

    @field_validator("longitude")
    @classmethod
    def lon_range(cls, v: float | None) -> float | None:
        if v is not None and not (-180 <= v <= 180):
            raise ValueError("longitude out of range")
        return v


# ── Processed telemetry event (persisted) ────────────────────────────────────

class TelemetryEventResponse(CamelBase):
    id: uuid.UUID
    device_id: str
    shipment_id: uuid.UUID | None
    tenant_id: uuid.UUID
    event_type: TelemetryEventType
    latitude: float | None
    longitude: float | None
    temperature_c: float | None
    humidity_pct: float | None
    shock_g: float | None
    battery_pct: int | None
    geofence_id: uuid.UUID | None
    geofence_name: str | None
    occurred_at: datetime
    processed_at: datetime
    alert_triggered: bool


# ── Geofences ─────────────────────────────────────────────────────────────────

class GeofenceCreate(CamelBase):
    name: str
    description: str | None = None
    # WKT polygon (WGS-84) or bounding box
    wkt_polygon: str | None = None
    # Simple bounding box alternative
    min_lat: float | None = None
    max_lat: float | None = None
    min_lon: float | None = None
    max_lon: float | None = None

    @model_validator(mode="after")
    def polygon_or_bbox(self) -> "GeofenceCreate":
        has_poly = self.wkt_polygon is not None
        has_bbox = all(
            v is not None for v in [self.min_lat, self.max_lat, self.min_lon, self.max_lon]
        )
        if not has_poly and not has_bbox:
            raise ValueError("Provide either wkt_polygon or a bounding box (min/max lat/lon)")
        return self


class GeofenceResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    wkt_polygon: str | None
    min_lat: float | None
    max_lat: float | None
    min_lon: float | None
    max_lon: float | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Device registration ───────────────────────────────────────────────────────

class DeviceCreate(CamelBase):
    device_id: str
    device_type: DeviceType
    shipment_id: uuid.UUID | None = None
    serial_number: str | None = None
    firmware_version: str | None = None


class DeviceResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    device_id: str
    device_type: DeviceType
    shipment_id: uuid.UUID | None
    serial_number: str | None
    firmware_version: str | None
    last_seen_at: datetime | None
    battery_pct: int | None
    is_active: bool
    created_at: datetime


# ── Telemetry query params ────────────────────────────────────────────────────

class TelemetryQueryParams(CamelBase):
    shipment_id: uuid.UUID | None = None
    device_id: str | None = None
    event_type: TelemetryEventType | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    limit: int = 100

    @field_validator("limit")
    @classmethod
    def cap_limit(cls, v: int) -> int:
        return min(v, 1000)
