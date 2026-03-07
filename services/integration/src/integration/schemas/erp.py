"""ERP event and entity schemas."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class ERPSystem(str, enum.Enum):
    SAP = "sap"
    ORACLE = "oracle"
    GENERIC = "generic"


class ERPEntityType(str, enum.Enum):
    PURCHASE_ORDER = "purchase_order"
    INVOICE = "invoice"
    SUPPLIER = "supplier"
    GOODS_RECEIPT = "goods_receipt"
    DELIVERY = "delivery"


class ERPConnectionConfig(BaseModel):
    """Tenant ERP connection settings (stored encrypted in DB)."""

    system: ERPSystem
    base_url: str
    client_id: str
    client_secret: str
    tenant_id: UUID
    timeout_seconds: int = 30
    extra: dict[str, Any] = Field(default_factory=dict)


class ERPPullRequest(BaseModel):
    tenant_id: UUID
    system: ERPSystem
    entity_type: ERPEntityType
    since: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=500)


class ERPRawEvent(BaseModel):
    """Normalised representation of one ERP entity/event."""

    source_system: ERPSystem
    entity_type: ERPEntityType
    source_id: str = Field(..., description="Primary key in source ERP system")
    tenant_id: UUID
    occurred_at: datetime
    payload: dict[str, Any]


class ERPSyncResult(BaseModel):
    tenant_id: UUID
    system: ERPSystem
    entity_type: ERPEntityType
    fetched: int
    published: int
    errors: int
    duration_ms: int


# ── ERP Supplier normalised ────────────────────────────────────────────────────

class NormalisedSupplier(BaseModel):
    source_id: str
    name: str
    country: str | None = None
    tax_id: str | None = None
    address: str | None = None
    contact_email: str | None = None
    active: bool = True
    raw: dict[str, Any] = Field(default_factory=dict)


# ── ERP Purchase Order normalised ─────────────────────────────────────────────

class NormalisedPurchaseOrder(BaseModel):
    source_id: str
    supplier_source_id: str
    amount: float
    currency: str = "USD"
    status: str
    issued_at: datetime
    due_at: datetime | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
