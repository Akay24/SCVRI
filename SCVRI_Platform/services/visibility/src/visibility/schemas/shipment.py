"""Shipment tracking schemas (pydantic v2)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import field_validator

from scvri_shared.schemas import CamelBase

# ── Enums ─────────────────────────────────────────────────────────────────────

ShipmentStatus = Literal[
    "pending",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "customs_hold",
    "exception",
    "delivered",
    "returned",
]

CarrierType = Literal[
    "ocean",
    "air",
    "road",
    "rail",
    "courier",
    "multimodal",
]

# ── Coordinates ───────────────────────────────────────────────────────────────

class GeoCoordinate(CamelBase):
    latitude: float
    longitude: float
    altitude_m: float | None = None

    @field_validator("latitude")
    @classmethod
    def lat_range(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("latitude must be -90..90")
        return v

    @field_validator("longitude")
    @classmethod
    def lon_range(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("longitude must be -180..180")
        return v


# ── Shipment Creation ─────────────────────────────────────────────────────────

class ShipmentCreate(CamelBase):
    po_id: uuid.UUID
    carrier: str
    carrier_type: CarrierType
    tracking_number: str
    origin_address: str
    destination_address: str
    origin_coords: GeoCoordinate | None = None
    destination_coords: GeoCoordinate | None = None
    estimated_arrival: datetime | None = None
    weight_kg: float | None = None
    volume_m3: float | None = None
    incoterm: str | None = None  # EXW, FOB, CIF, DDP, etc.
    notes: str | None = None


class ShipmentUpdate(CamelBase):
    estimated_arrival: datetime | None = None
    tracking_number: str | None = None
    notes: str | None = None


# ── Tracking Events ───────────────────────────────────────────────────────────

class TrackingEventCreate(CamelBase):
    shipment_id: uuid.UUID
    event_type: Literal[
        "picked_up",
        "departed",
        "arrived",
        "in_transit",
        "customs_cleared",
        "customs_hold",
        "out_for_delivery",
        "delivered",
        "exception",
        "returned",
    ]
    location: str
    coords: GeoCoordinate | None = None
    carrier_reference: str | None = None
    description: str | None = None
    occurred_at: datetime


class TrackingEventResponse(CamelBase):
    id: uuid.UUID
    shipment_id: uuid.UUID
    event_type: str
    location: str
    coords: GeoCoordinate | None = None
    carrier_reference: str | None = None
    description: str | None = None
    occurred_at: datetime
    created_at: datetime


# ── Shipment Response ─────────────────────────────────────────────────────────

class ShipmentResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    po_id: uuid.UUID
    carrier: str
    carrier_type: CarrierType
    tracking_number: str
    status: ShipmentStatus
    origin_address: str
    destination_address: str
    origin_coords: GeoCoordinate | None = None
    destination_coords: GeoCoordinate | None = None
    current_coords: GeoCoordinate | None = None
    current_location: str | None = None
    estimated_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    weight_kg: float | None = None
    volume_m3: float | None = None
    incoterm: str | None = None
    notes: str | None = None
    events: list[TrackingEventResponse] = []
    created_at: datetime
    updated_at: datetime


# ── ETA Prediction ────────────────────────────────────────────────────────────

class ETAPredictionResponse(CamelBase):
    shipment_id: uuid.UUID
    current_estimated_arrival: datetime | None
    predicted_arrival: datetime
    confidence_days: float  # ±N days confidence interval
    delay_risk: Literal["low", "medium", "high"]
    delay_factors: list[str]  # human-readable reasons


# ── Shipment KPI ──────────────────────────────────────────────────────────────

class ShipmentKPIResponse(CamelBase):
    supplier_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    total_shipments: int
    on_time_deliveries: int
    delayed_deliveries: int
    in_customs_hold: int
    avg_transit_days: float
    otd_rate: float  # 0-100
