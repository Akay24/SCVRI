"""Purchase Order and PO Line Item models.

Citus distribution key: tenant_id.
Monthly range partitioning on po_date handled in Alembic DDL migration.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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
    from scvri_shared.models.supplier import Supplier
    from scvri_shared.models.shipment import Shipment


POStatus = Enum(
    "draft",
    "submitted",
    "acknowledged",
    "in_production",
    "shipped",
    "partially_received",
    "received",
    "invoiced",
    "closed",
    "cancelled",
    name="po_status_enum",
    schema="supply_chain",
)


class PurchaseOrder(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Purchase order header.

    Partitioned by ``po_date`` (monthly) — handled in DDL migration.
    Citus shards on tenant_id.
    """

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "po_number", name="uq_po_tenant_number"),
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_po_supplier",
            ondelete="RESTRICT",
        ),
        Index("idx_po_tenant_supplier", "tenant_id", "supplier_id"),
        Index("idx_po_tenant_date", "tenant_id", "po_date"),
        Index("idx_po_status", "tenant_id", "status"),
        {"schema": "supply_chain"},
    )

    # ------------------------------------------------------------------ #
    # Core fields
    # ------------------------------------------------------------------ #
    po_number: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        POStatus, nullable=False, server_default="draft"
    )

    # ------------------------------------------------------------------ #
    # Dates
    # ------------------------------------------------------------------ #
    po_date: Mapped[date] = mapped_column(Date, nullable=False)
    required_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ------------------------------------------------------------------ #
    # Financials
    # ------------------------------------------------------------------ #
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD"
    )  # ISO 4217
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0.00"
    )
    invoiced_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0.00"
    )
    payment_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ------------------------------------------------------------------ #
    # Delivery & Risk fields
    # ------------------------------------------------------------------ #
    incoterms: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(2), nullable=True)
    is_at_risk: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )  # set by risk engine
    risk_flags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # ERP integration
    # ------------------------------------------------------------------ #
    erp_po_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    erp_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    erp_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="purchase_orders", lazy="noload")
    line_items: Mapped[list[POLineItem]] = relationship(
        "POLineItem",
        back_populates="purchase_order",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    shipments: Mapped[list[Shipment]] = relationship(
        "Shipment", back_populates="purchase_order", lazy="noload"
    )


class POLineItem(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Individual line item within a purchase order."""

    __tablename__ = "po_line_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["po_id", "tenant_id"],
            ["supply_chain.purchase_orders.id", "supply_chain.purchase_orders.tenant_id"],
            name="fk_line_item_po",
            ondelete="CASCADE",
        ),
        Index("idx_line_item_po", "tenant_id", "po_id"),
        {"schema": "supply_chain"},
    )

    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_ordered: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False
    )
    quantity_received: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, server_default="0.0000"
    )
    unit_of_measure: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    commodity_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    purchase_order: Mapped[PurchaseOrder] = relationship(
        "PurchaseOrder", back_populates="line_items", lazy="noload"
    )
