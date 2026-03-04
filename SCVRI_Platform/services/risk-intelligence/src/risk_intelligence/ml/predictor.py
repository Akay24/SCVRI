"""Predictor — orchestrates feature engineering → model inference → risk score.

The champion model is loaded lazily on the first request and cached.
Feature names are fixed and MUST match the order expected by trained models.

Scoring output:
  - risk_score: 0-100 (higher = more risk)
  - risk_level: critical | high | medium | low | minimal
  - component breakdown for transparency
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import numpy as np

from scvri_shared.logging import get_logger
from risk_intelligence.ml.model_loader import load_model, predict_proba
from risk_intelligence.schemas.model import FeatureVector
from risk_intelligence.schemas.risk_score import RiskComponentScore

log = get_logger(__name__)

# Canonical feature order — MUST stay in sync with model training pipelines
FEATURE_NAMES: list[str] = [
    "otd_rate",
    "fill_rate",
    "defect_rate",
    "invoice_accuracy_rate",
    "overall_scorecard_score",
    "scorecard_age_days",
    "composite_kri_score",
    "kri_red_count",
    "kri_amber_count",
    "supplier_tier_encoded",
    "onboarding_status_encoded",
    "years_in_business",
    "employee_count_log",
    "country_risk_score",
    "active_certifications_count",
    "expired_certifications_count",
    "compliance_violations_count",
    "is_sole_source",
    "spend_concentration_pct",
]

# Risk level thresholds (risk_score 0-100)
_THRESHOLDS = {
    "critical": 80,
    "high":     60,
    "medium":   40,
    "low":      20,
    # below 20 → minimal
}


@dataclass
class PredictionResult:
    risk_score: float                           # 0-100
    risk_level: str                             # critical/high/medium/low/minimal
    components: list[RiskComponentScore]
    model_id: str
    model_version: str
    latency_ms: float


def score_to_level(risk_score: float) -> str:
    if risk_score >= _THRESHOLDS["critical"]:
        return "critical"
    if risk_score >= _THRESHOLDS["high"]:
        return "high"
    if risk_score >= _THRESHOLDS["medium"]:
        return "medium"
    if risk_score >= _THRESHOLDS["low"]:
        return "low"
    return "minimal"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def predict(
    fv: FeatureVector,
    artifact_path: str,
    framework: str,
    model_id: str,
    model_version: str,
) -> PredictionResult:
    """Run inference synchronously (called from Celery worker + asyncio.run wrapper)."""
    t0 = time.perf_counter()

    model = load_model(artifact_path, framework)

    feature_array = np.array([[
        getattr(fv, name, 0.0) for name in FEATURE_NAMES
    ]], dtype=np.float32)

    proba = predict_proba(model, feature_array)
    risk_score = round(proba * 100, 2)
    risk_level = score_to_level(risk_score)

    components = _build_component_scores(fv)
    latency = round((time.perf_counter() - t0) * 1000, 2)

    log.info(
        "predictor.scored",
        supplier_id=str(fv.supplier_id),
        risk_score=risk_score,
        risk_level=risk_level,
        model_id=model_id,
        latency_ms=latency,
    )
    return PredictionResult(
        risk_score=risk_score,
        risk_level=risk_level,
        components=components,
        model_id=model_id,
        model_version=model_version,
        latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# Component score decomposition (for explainability)
# ---------------------------------------------------------------------------
def _build_component_scores(fv: FeatureVector) -> list[RiskComponentScore]:
    """Derive human-readable component scores from the feature vector."""
    components = []

    # Operational Performance (scorecard-based)
    op_risk = (
        (100 - fv.otd_rate) * 0.35
        + (100 - fv.fill_rate) * 0.25
        + fv.defect_rate * 0.25
        + (100 - fv.invoice_accuracy_rate) * 0.15
    )
    factors = []
    if fv.otd_rate < 80:
        factors.append(f"OTD rate below threshold ({fv.otd_rate:.1f}%)")
    if fv.defect_rate > 5:
        factors.append(f"Elevated defect rate ({fv.defect_rate:.1f}%)")
    if fv.scorecard_age_days > 90:
        factors.append(f"Stale scorecard ({fv.scorecard_age_days} days old)")
    components.append(RiskComponentScore(
        component="operational_performance",
        score=round(op_risk, 2),
        weight=0.35,
        contributing_factors=factors,
        data_freshness_days=fv.scorecard_age_days if fv.scorecard_age_days < 999 else None,
    ))

    # KRI Risk
    kri_risk = fv.composite_kri_score
    kri_factors = []
    if fv.kri_red_count > 0:
        kri_factors.append(f"{fv.kri_red_count} KRI(s) in RED status")
    if fv.kri_amber_count > 0:
        kri_factors.append(f"{fv.kri_amber_count} KRI(s) in AMBER status")
    components.append(RiskComponentScore(
        component="kri_composite",
        score=round(kri_risk, 2),
        weight=0.25,
        contributing_factors=kri_factors,
    ))

    # Geopolitical / Country Risk
    geo_factors = []
    if fv.country_risk_score > 60:
        geo_factors.append(f"High country risk score ({fv.country_risk_score:.0f}/100)")
    components.append(RiskComponentScore(
        component="geopolitical",
        score=round(fv.country_risk_score, 2),
        weight=0.15,
        contributing_factors=geo_factors,
    ))

    # Compliance / Certification
    comp_risk = 0.0
    comp_factors = []
    if fv.expired_certifications_count > 0:
        comp_risk += min(fv.expired_certifications_count * 15, 60)
        comp_factors.append(f"{fv.expired_certifications_count} expired certification(s)")
    if fv.compliance_violations_count > 0:
        comp_risk += min(fv.compliance_violations_count * 20, 40)
        comp_factors.append(f"{fv.compliance_violations_count} compliance violation(s)")
    if fv.active_certifications_count == 0:
        comp_risk += 20
        comp_factors.append("No active certifications on file")
    components.append(RiskComponentScore(
        component="compliance",
        score=round(min(comp_risk, 100), 2),
        weight=0.15,
        contributing_factors=comp_factors,
    ))

    # Concentration Risk
    conc_risk = 0.0
    conc_factors = []
    if fv.is_sole_source:
        conc_risk += 40
        conc_factors.append("Sole-source supplier")
    if fv.spend_concentration_pct > 30:
        conc_risk += min((fv.spend_concentration_pct - 30) * 1.5, 50)
        conc_factors.append(f"High spend concentration ({fv.spend_concentration_pct:.1f}%)")
    components.append(RiskComponentScore(
        component="concentration",
        score=round(min(conc_risk, 100), 2),
        weight=0.10,
        contributing_factors=conc_factors,
    ))

    return components
