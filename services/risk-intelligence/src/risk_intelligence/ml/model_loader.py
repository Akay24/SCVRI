"""Model loader — loads serialised ML models from S3 (MinIO in dev) and caches them.

Supports:
  - XGBoost  (.ubj binary format)
  - LightGBM (.txt text format)
  - scikit-learn pipelines (.joblib)
  - rule_based (no artifact — built-in heuristic)

Model objects are cached in a process-local LRU cache keyed by (model_id, version).
Cache is invalidated when a new champion is promoted (handled by clearing the cache
and reloading on next request).
"""
from __future__ import annotations

import io
import os
import uuid
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

import joblib

from scvri_shared.config import settings
from scvri_shared.logging import get_logger

log = get_logger(__name__)

_CACHE: dict[str, Any] = {}          # {artifact_path: model_object}


@runtime_checkable
class ScikitPredictor(Protocol):
    def predict_proba(self, X) -> Any: ...


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_model(artifact_path: str, framework: str) -> Any:
    """Load a model from S3, returning a framework-specific model object.

    Results are cached in the module-level _CACHE dict by artifact_path.
    """
    if artifact_path in _CACHE:
        return _CACHE[artifact_path]

    if framework == "rule_based":
        model = _RuleBasedModel()
        _CACHE[artifact_path] = model
        return model

    raw_bytes = _download_from_s3(artifact_path)

    if framework == "xgboost":
        import xgboost as xgb  # noqa: PLC0415
        bst = xgb.Booster()
        bst.load_model(bytearray(raw_bytes))
        _CACHE[artifact_path] = bst
        return bst

    if framework == "lightgbm":
        import lightgbm as lgb  # noqa: PLC0415
        buf = io.StringIO(raw_bytes.decode("utf-8"))
        bst = lgb.Booster(model_str=buf.read())
        _CACHE[artifact_path] = bst
        return bst

    if framework == "sklearn":
        model = joblib.load(io.BytesIO(raw_bytes))
        _CACHE[artifact_path] = model
        return model

    raise ValueError(f"Unknown model framework: {framework!r}")


def evict_cache(artifact_path: str | None = None) -> None:
    """Evict one entry (or entire cache if path is None)."""
    if artifact_path is None:
        _CACHE.clear()
        log.info("model_cache.cleared")
    elif artifact_path in _CACHE:
        del _CACHE[artifact_path]
        log.info("model_cache.evicted", artifact_path=artifact_path)


def predict_proba(model: Any, feature_array) -> float:
    """Return a risk probability [0-1] for a single sample.

    feature_array: numpy array shape (1, n_features)
    """
    import numpy as np  # noqa: PLC0415

    if isinstance(model, _RuleBasedModel):
        return model.predict_proba(feature_array)

    framework = type(model).__module__.split(".")[0]

    if framework == "xgboost":
        import xgboost as xgb  # noqa: PLC0415
        dmatrix = xgb.DMatrix(feature_array)
        proba = model.predict(dmatrix)[0]
        return float(np.clip(proba, 0.0, 1.0))

    if framework == "lightgbm":
        proba = model.predict(feature_array)[0]
        return float(np.clip(proba, 0.0, 1.0))

    # sklearn / pipeline
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(feature_array)[0]
        # Binary classification: proba[1] = P(high risk)
        return float(np.clip(proba[1], 0.0, 1.0))
    if hasattr(model, "predict"):
        score = model.predict(feature_array)[0]
        return float(np.clip(score, 0.0, 1.0))

    raise TypeError(f"Cannot perform inference on model type {type(model)}")


# ---------------------------------------------------------------------------
# S3 download
# ---------------------------------------------------------------------------
def _download_from_s3(artifact_path: str) -> bytes:
    import boto3  # noqa: PLC0415
    from botocore.exceptions import ClientError  # noqa: PLC0415

    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        # MinIO endpoint for dev
        endpoint_url=getattr(settings, "s3_endpoint_url", None),
    )
    buf = io.BytesIO()
    try:
        s3.download_fileobj(settings.s3_ml_artifacts_bucket, artifact_path, buf)
    except ClientError as exc:
        log.error("model_loader.s3_download_failed", path=artifact_path, error=str(exc))
        raise
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Rule-based fallback model (no ML artifact required)
# ---------------------------------------------------------------------------
class _RuleBasedModel:
    """Deterministic rule-based scorer used when no ML model is available.

    Returns a risk probability [0-1] based on weighted heuristics.
    Feature index order matches FEATURE_NAMES in predictor.py.
    """

    def predict_proba(self, feature_array) -> float:
        import numpy as np  # noqa: PLC0415

        f = feature_array[0] if hasattr(feature_array, "__len__") else feature_array

        # f is ordered per FEATURE_NAMES in predictor.py
        # [otd_rate, fill_rate, defect_rate, invoice_accuracy_rate,
        #  overall_scorecard_score, scorecard_age_days, composite_kri_score,
        #  kri_red_count, kri_amber_count, supplier_tier_encoded,
        #  onboarding_status_encoded, years_in_business, employee_count_log,
        #  country_risk_score, active_certifications_count,
        #  expired_certifications_count, compliance_violations_count,
        #  is_sole_source, spend_concentration_pct]

        try:
            otd = float(f[0]) / 100.0
            fill = float(f[1]) / 100.0
            defect = float(f[2]) / 100.0
            scorecard_age = float(f[5]) / 365.0
            kri_red = int(f[7])
            country_risk = float(f[13]) / 100.0
            compliance_violations = int(f[16])
            is_sole = bool(f[17])
        except (IndexError, TypeError):
            return 0.5

        risk = (
            (1 - otd) * 0.25
            + (1 - fill) * 0.20
            + defect * 0.15
            + min(scorecard_age, 1.0) * 0.10
            + min(kri_red / 5.0, 1.0) * 0.15
            + country_risk * 0.10
            + min(compliance_violations / 3.0, 1.0) * 0.05
        )
        if is_sole:
            risk = min(risk + 0.1, 1.0)

        return float(np.clip(risk, 0.0, 1.0))
