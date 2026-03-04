"""Risk score schemas — request/response models for scoring endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from scvri_shared.schemas import CamelBase, TimestampSchema

RiskLevel = Literal["critical", "high", "medium", "low", "minimal"]


# ---------------------------------------------------------------------------
# Component scores (sub-dimensions of risk)
# ---------------------------------------------------------------------------
class RiskComponentScore(CamelBase):
    """Individual risk dimension score."""
    component: str
    score: float          # 0-100 (higher = more risk)
    weight: float         # 0-1 fraction
    contributing_factors: list[str] = []
    data_freshness_days: int | None = None


class SupplierRiskScoreRequest(CamelBase):
    """Trigger a risk score computation for a specific supplier."""
    supplier_id: uuid.UUID
    force_recompute: bool = False
    model_id: str | None = None  # None = use champion model


class SupplierRiskScoreResponse(CamelBase):
    """Full risk score response with component breakdown."""
    id: uuid.UUID
    supplier_id: uuid.UUID
    tenant_id: uuid.UUID
    overall_score: float          # 0-100 composite (higher = more risk)
    risk_level: RiskLevel
    previous_score: float | None = None
    score_delta: float | None = None
    components: list[RiskComponentScore] = []
    model_id: str
    model_version: str
    computed_at: datetime
    valid_until: datetime | None = None
    explanation: str | None = None  # LLM-generated natural language summary
    created_at: datetime | None = None


class SupplierRiskSummary(CamelBase):
    """Lightweight risk summary for list views."""
    supplier_id: uuid.UUID
    overall_score: float
    risk_level: RiskLevel
    score_delta: float | None = None
    computed_at: datetime


class RiskScoreHistoryPoint(CamelBase):
    overall_score: float
    risk_level: RiskLevel
    computed_at: datetime


class RiskScoreHistoryResponse(CamelBase):
    supplier_id: uuid.UUID
    data_points: list[RiskScoreHistoryPoint]


class BulkRiskScoreRequest(CamelBase):
    """Trigger risk score computation for a list of up to 200 suppliers."""
    supplier_ids: list[uuid.UUID]
    force_recompute: bool = False

    from pydantic import field_validator

    @field_validator("supplier_ids")
    @classmethod
    def check_max(cls, v: list) -> list:
        if len(v) > 200:
            raise ValueError("Maximum 200 supplier IDs per bulk request")
        return v


class TenantRiskSummaryResponse(CamelBase):
    """Aggregate risk distribution across all suppliers for a tenant."""
    tenant_id: uuid.UUID
    total_suppliers: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    minimal_count: int
    unscored_count: int
    avg_risk_score: float
    computed_at: datetime
