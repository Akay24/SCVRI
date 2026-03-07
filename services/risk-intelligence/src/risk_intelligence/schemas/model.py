"""ML model registry schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from scvri_shared.schemas import CamelBase

ModelStatus = Literal["staging", "champion", "challenger", "archived", "failed"]
ModelFramework = Literal["xgboost", "lightgbm", "sklearn", "rule_based"]


class ModelArtifactUploadRequest(CamelBase):
    """Request to register a new model version."""
    name: str
    version: str
    framework: ModelFramework
    description: str | None = None
    feature_names: list[str]
    hyperparameters: dict = {}
    training_dataset_id: str | None = None     # reference to training run/dataset
    metrics: dict[str, float] = {}             # e.g. {"auc": 0.87, "f1": 0.81}
    artifact_path: str                         # S3 key under ml-artifacts bucket


class ModelResponse(CamelBase):
    id: uuid.UUID
    name: str
    version: str
    framework: ModelFramework
    description: str | None
    feature_names: list[str]
    hyperparameters: dict
    metrics: dict[str, float]
    artifact_path: str
    status: ModelStatus
    is_champion: bool
    promoted_at: datetime | None
    created_at: datetime
    created_by: uuid.UUID | None


class ModelPromoteRequest(CamelBase):
    """Promote a model to champion status (demotes current champion → archived)."""
    model_id: uuid.UUID
    reason: str


class ModelPredictRequest(CamelBase):
    """Direct model inference request (used for A/B testing and debugging)."""
    model_id: uuid.UUID
    features: dict[str, float]


class ModelPredictResponse(CamelBase):
    model_id: uuid.UUID
    model_version: str
    risk_score: float
    risk_level: str
    feature_importances: dict[str, float] = {}
    prediction_latency_ms: float


class FeatureVector(CamelBase):
    """Assembled feature vector before model inference."""
    supplier_id: uuid.UUID
    tenant_id: uuid.UUID
    # Scorecard-derived (operational)
    otd_rate: float = 50.0
    fill_rate: float = 50.0
    defect_rate: float = 0.0
    invoice_accuracy_rate: float = 100.0
    overall_scorecard_score: float = 50.0
    scorecard_age_days: int = 999          # days since last scorecard
    # KRI-derived
    composite_kri_score: float = 50.0
    kri_red_count: int = 0
    kri_amber_count: int = 0
    # Supplier attributes
    supplier_tier_encoded: float = 0.5    # tier_1=1.0, tier_2=0.75, tier_3=0.5, etc.
    onboarding_status_encoded: float = 1.0  # active=1.0, suspended=0.5
    years_in_business: float = 5.0
    employee_count_log: float = 5.0       # log10(employee_count)
    # Country / geopolitical
    country_risk_score: float = 30.0      # 0-100 from external API
    # Compliance
    active_certifications_count: int = 0
    expired_certifications_count: int = 0
    compliance_violations_count: int = 0
    # Concentration risk
    is_sole_source: bool = False
    spend_concentration_pct: float = 0.0  # % of total spend this supplier represents
