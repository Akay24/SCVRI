"""KRI (Key Risk Indicator) schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import field_validator

from scvri_shared.schemas import CamelBase

KRIStatus = Literal["green", "amber", "red"]
KRICategory = Literal[
    "financial", "operational", "geopolitical", "compliance",
    "cyber", "esg", "concentration", "reputational"
]
AggregationMethod = Literal["latest", "avg_30d", "max_30d", "min_30d", "count_30d"]


class KRIDefinitionCreate(CamelBase):
    """Define a new KRI metric for a tenant."""
    name: str
    description: str
    category: KRICategory
    unit: str                           # e.g. '%', 'days', 'count', 'score'
    aggregation_method: AggregationMethod = "latest"
    green_threshold: float              # value <= green → GREEN
    amber_threshold: float              # green < value <= amber → AMBER
    # value > amber_threshold → RED
    weight: float = 1.0                 # weight in composite KRI score
    is_inverted: bool = False           # True = lower value is worse (e.g. cash_ratio)
    is_global: bool = False             # Global KRI visible to all tenants
    data_source: str | None = None      # e.g. 'scorecard', 'financial_api', 'manual'

    @field_validator("weight")
    @classmethod
    def valid_weight(cls, v: float) -> float:
        if not (0 < v <= 5.0):
            raise ValueError("weight must be between 0 (exclusive) and 5.0")
        return v


class KRIDefinitionResponse(CamelBase):
    id: uuid.UUID
    name: str
    description: str
    category: KRICategory
    unit: str
    aggregation_method: AggregationMethod
    green_threshold: float
    amber_threshold: float
    weight: float
    is_inverted: bool
    is_global: bool
    data_source: str | None
    tenant_id: uuid.UUID | None
    created_at: datetime


class KRISnapshotCreate(CamelBase):
    """Record a KRI measurement for a supplier."""
    supplier_id: uuid.UUID
    kri_definition_id: uuid.UUID
    value: float
    raw_data: dict | None = None        # source payload for auditability


class KRISnapshotResponse(CamelBase):
    id: uuid.UUID
    supplier_id: uuid.UUID
    kri_definition_id: uuid.UUID
    kri_name: str
    category: KRICategory
    value: float
    status: KRIStatus
    unit: str
    measured_at: datetime


class SupplierKRIDashboard(CamelBase):
    """All KRI readings for one supplier, grouped by category."""
    supplier_id: uuid.UUID
    snapshots: list[KRISnapshotResponse]
    red_count: int
    amber_count: int
    green_count: int
    composite_kri_score: float          # 0-100 aggregate
    last_evaluated_at: datetime | None


class KRIThresholdBreachEvent(CamelBase):
    """Emitted to Kafka when a KRI crosses amber/red threshold."""
    supplier_id: uuid.UUID
    tenant_id: uuid.UUID
    kri_definition_id: uuid.UUID
    kri_name: str
    category: KRICategory
    previous_status: KRIStatus
    new_status: KRIStatus
    value: float
    threshold: float
    measured_at: datetime
