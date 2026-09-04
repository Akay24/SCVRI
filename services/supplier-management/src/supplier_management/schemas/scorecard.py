"""Pydantic schemas for supplier scorecards."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field, model_validator

from scvri_shared.schemas import CamelBase, TimestampSchema


class ScorecardCreate(CamelBase):
    """Input for manually triggering a scorecard computation."""
    period_start: date
    period_end: date
    total_deliveries: int = Field(ge=0)
    on_time_deliveries: int = Field(ge=0)
    items_ordered: int = Field(default=0, ge=0)
    items_received: int = Field(default=0, ge=0)
    returned_items: int = Field(default=0, ge=0)
    invoice_discrepancy_pct: float = Field(default=0.0, ge=0.0, le=100.0)

    # Alternate naming support (e.g. quantity_ordered, quantity_received, quantity_returned)
    quantity_ordered: int | None = None
    quantity_received: int | None = None
    quantity_returned: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_quantities(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "quantity_ordered" in data and "items_ordered" not in data:
                data["items_ordered"] = data["quantity_ordered"]
            if "quantity_received" in data and "items_received" not in data:
                data["items_received"] = data["quantity_received"]
            if "quantity_returned" in data and "returned_items" not in data:
                data["returned_items"] = data["quantity_returned"]
        return data

    @model_validator(mode="after")
    def validate_counts(self) -> "ScorecardCreate":
        if self.on_time_deliveries > self.total_deliveries:
            raise ValueError("on_time_deliveries cannot exceed total_deliveries")
        if self.items_received > self.items_ordered:
            raise ValueError("items_received cannot exceed items_ordered")
        if self.returned_items > self.items_received:
            raise ValueError("returned_items cannot exceed items_received")
        return self


class ScorecardResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    period_start: date
    period_end: date
    total_deliveries: int
    on_time_deliveries: int
    items_ordered: int
    items_received: int
    returned_items: int
    invoice_discrepancy_pct: float
    # Computed by DB trigger
    otd_rate: float
    defect_rate: float
    fill_rate: float
    invoice_accuracy: float
    overall_score: float
    grade: str          # A / B / C / D
    formula_version: str
    computed_by: str


class ScorecardTrendPoint(CamelBase):
    period_start: date
    period_end: date
    overall_score: float
    grade: str
    otd_rate: float
    defect_rate: float


class ScorecardTrendResponse(CamelBase):
    supplier_id: uuid.UUID
    data_points: list[ScorecardTrendPoint]
