"""Shipment and IoT Telemetry models.

Shipments track physical movement of goods.
IoTBreach events are stored in iot_telemetry (partitioned monthly).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scvri_shared.models.base import (
    Base,
    TimestampMixin,
    TenantMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from scvri_shared.models.purchase_order import PurchaseOrder
    from scvri_shared.models.supplier import Supplier


ShipmentStatus = Enum(
    "booked",
    "in_transit",
    "at_port",
    "customs_hold",
    "out_for_delivery",
    "delivered",
    "exception",
    "returned",
    "cancelled",
    name="shipment_status_enum",
    schema="supply_chain",
)

TransportMode = Enum(
    "ocean",
    "air",
    "road",
    "rail",
    "multimodal",
    name="transport_mode_enum",
    schema="supply_chain",
)


class Shipment(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Shipment record — tracks a physical movement from supplier to destination."""

    __tablename__ = "shipments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["po_id", "tenant_id"],
            ["supply_chain.purchase_orders.id", "supply_chain.purchase_orders.tenant_id"],
            name="fk_shipment_po",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_shipment_supplier",
            ondelete="RESTRICT",
        ),
        Index("idx_shipment_po", "tenant_id", "po_id"),
        Index("idx_shipment_supplier", "tenant_id", "supplier_id"),
        Index("idx_shipment_status", "tenant_id", "status"),
        Index("idx_shipment_eta", "tenant_id", "estimated_arrival"),
        {"schema": "supply_chain"},
    )

    # ------------------------------------------------------------------ #
    # Core
    # ------------------------------------------------------------------ #
    tracking_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bill_of_lading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    carrier_scac: Mapped[str | None] = mapped_column(
        String(4), nullable=True
    )  # Standard Carrier Alpha Code
    transport_mode: Mapped[str | None] = mapped_column(TransportMode, nullable=True)
    status: Mapped[str] = mapped_column(
        ShipmentStatus, nullable=False, server_default="booked"
    )

    # ------------------------------------------------------------------ #
    # References
    # ------------------------------------------------------------------ #
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # ------------------------------------------------------------------ #
    # Locations
    # ------------------------------------------------------------------ #
    origin_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    origin_port: Mapped[str | None] = mapped_column(String(10), nullable=True)  # UNLOCODE
    destination_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    destination_port: Mapped[str | None] = mapped_column(String(10), nullable=True)
    current_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    current_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)

    # ------------------------------------------------------------------ #
    # Dates
    # ------------------------------------------------------------------ #
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_arrival: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_arrival: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Performance flag (populated by risk engine)
    # ------------------------------------------------------------------ #
    is_delayed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delay_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ------------------------------------------------------------------ #
    # ERP integration
    # ------------------------------------------------------------------ #
    erp_shipment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    purchase_order: Mapped[PurchaseOrder] = relationship(
        "PurchaseOrder", back_populates="shipments", lazy="noload"
    )
    supplier: Mapped[Supplier] = relationship("Supplier", lazy="noload")
    events: Mapped[list[ShipmentEvent]] = relationship(
        "ShipmentEvent",
        back_populates="shipment",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="ShipmentEvent.occurred_at.asc()",
    )
    iot_readings: Mapped[list[IoTTelemetry]] = relationship(
        "IoTTelemetry", back_populates="shipment", lazy="noload"
    )


class ShipmentEvent(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Immutable audit trail of shipment status transitions."""

    __tablename__ = "shipment_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shipment_id", "tenant_id"],
            ["supply_chain.shipments.id", "supply_chain.shipments.tenant_id"],
            name="fk_shipment_event",
            ondelete="CASCADE",
        ),
        Index("idx_shipment_event_occurred", "tenant_id", "shipment_id", "occurred_at"),
        {"schema": "supply_chain"},
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # tms | edi | manual | iot

    shipment: Mapped[Shipment] = relationship("Shipment", back_populates="events", lazy="noload")


class IoTTelemetry(Base, UUIDPrimaryKeyMixin, TenantMixin):
    """IoT sensor readings for cold-chain and high-value shipments.

    Partitioned monthly on ``recorded_at``.
    18-month hot storage → S3 WORM archive via Kafka S3 Sink.
    """

    __tablename__ = "iot_telemetry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shipment_id", "tenant_id"],
            ["supply_chain.shipments.id", "supply_chain.shipments.tenant_id"],
            name="fk_iot_shipment",
            ondelete="CASCADE",
        ),
        Index("idx_iot_shipment_time", "tenant_id", "shipment_id", "recorded_at"),
        {"schema": "supply_chain"},
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # partition key

    # ------------------------------------------------------------------ #
    # Sensor readings
    # ------------------------------------------------------------------ #
    temperature_celsius: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    shock_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)

    # ------------------------------------------------------------------ #
    # Alert flags
    # ------------------------------------------------------------------ #
    is_breach: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    breach_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # temperature | humidity | shock | geofence
    thresholds: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    shipment: Mapped[Shipment] = relationship("Shipment", back_populates="iot_readings", lazy="noload")
