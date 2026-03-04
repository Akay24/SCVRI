"""Purchase Order schemas (pydantic v2)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import field_validator, model_validator

from scvri_shared.schemas import CamelBase, PaginatedResponse  # noqa: F401

# ── Enums ─────────────────────────────────────────────────────────────────────

POStatus = Literal[
    "draft",
    "confirmed",
    "partially_shipped",
    "shipped",
    "partially_received",
    "received",
    "cancelled",
    "disputed",
]

POLineStatus = Literal[
    "open",
    "partially_shipped",
    "shipped",
    "received",
    "cancelled",
]

# ── State-machine transitions ─────────────────────────────────────────────────
# Maps (current_status, event) → next_status
PO_TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "confirm"):           "confirmed",
    ("confirmed", "ship_partial"):  "partially_shipped",
    ("confirmed", "ship_complete"): "shipped",
    ("partially_shipped", "ship_partial"):  "partially_shipped",
    ("partially_shipped", "ship_complete"): "shipped",
    ("shipped", "receive_partial"):  "partially_received",
    ("shipped", "receive_complete"): "received",
    ("partially_received", "receive_partial"):  "partially_received",
    ("partially_received", "receive_complete"): "received",
    # Cancellation allowed from non-terminal states before shipped
    ("draft", "cancel"):      "cancelled",
    ("confirmed", "cancel"):  "cancelled",
    # Dispute
    ("shipped", "dispute"):           "disputed",
    ("partially_received", "dispute"): "disputed",
    ("received", "dispute"):           "disputed",
    ("disputed", "resolve"):           "received",
}

TERMINAL_PO_STATUSES = {"received", "cancelled"}


# ── PO Line ───────────────────────────────────────────────────────────────────

class POLineCreate(CamelBase):
    line_number: int
    product_code: str
    product_description: str
    quantity_ordered: float
    unit_of_measure: str
    unit_price: float
    currency: str = "USD"
    requested_delivery_date: datetime | None = None


class POLineResponse(CamelBase):
    id: uuid.UUID
    po_id: uuid.UUID
    line_number: int
    product_code: str
    product_description: str
    quantity_ordered: float
    quantity_shipped: float
    quantity_received: float
    unit_of_measure: str
    unit_price: float
    currency: str
    status: POLineStatus
    requested_delivery_date: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Purchase Order ─────────────────────────────────────────────────────────────

class PurchaseOrderCreate(CamelBase):
    supplier_id: uuid.UUID
    po_number: str
    currency: str = "USD"
    requested_delivery_date: datetime | None = None
    shipping_address: str | None = None
    notes: str | None = None
    lines: list[POLineCreate]

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("A purchase order must have at least one line item")
        return v

    @field_validator("po_number")
    @classmethod
    def po_number_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("po_number cannot be blank")
        return v.strip().upper()


class PurchaseOrderUpdate(CamelBase):
    requested_delivery_date: datetime | None = None
    shipping_address: str | None = None
    notes: str | None = None


class PurchaseOrderResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    po_number: str
    status: POStatus
    currency: str
    total_value: float
    requested_delivery_date: datetime | None = None
    confirmed_at: datetime | None = None
    first_shipped_at: datetime | None = None
    fully_shipped_at: datetime | None = None
    first_received_at: datetime | None = None
    fully_received_at: datetime | None = None
    cancelled_at: datetime | None = None
    shipping_address: str | None = None
    notes: str | None = None
    lines: list[POLineResponse] = []
    created_at: datetime
    updated_at: datetime


# ── PO Events (state transitions) ─────────────────────────────────────────────

class POEventRequest(CamelBase):
    event: Literal[
        "confirm",
        "ship_partial",
        "ship_complete",
        "receive_partial",
        "receive_complete",
        "cancel",
        "dispute",
        "resolve",
    ]
    notes: str | None = None
    # For ship/receive partial — optional line-level quantities
    line_updates: list[POLineShipment] = []


class POLineShipment(CamelBase):
    line_id: uuid.UUID
    quantity: float

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


# Fix forward reference
POEventRequest.model_rebuild()


# ── Delivery Performance ───────────────────────────────────────────────────────

class PODeliveryMetrics(CamelBase):
    supplier_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    total_pos: int
    on_time_count: int
    late_count: int
    otd_rate: float  # percentage (0-100)
    avg_days_late: float
    avg_lead_time_days: float
