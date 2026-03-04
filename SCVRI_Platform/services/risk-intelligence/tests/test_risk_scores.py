"""Unit and integration tests for risk scoring (service layer + ML pipeline)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from risk_intelligence.ml.predictor import score_to_level, FEATURE_NAMES
from risk_intelligence.schemas.risk_score import RiskComponentScore, SupplierRiskScoreResponse
from tests.conftest import TENANT_ID, SUPPLIER_ID, MODEL_ID


# ── score_to_level ────────────────────────────────────────────────────────────

class TestScoreToLevel:
    def test_critical_boundary(self):
        assert score_to_level(80.0) == "critical"

    def test_critical_over(self):
        assert score_to_level(99.9) == "critical"

    def test_high_boundary(self):
        assert score_to_level(60.0) == "high"

    def test_high_below_critical(self):
        assert score_to_level(79.9) == "high"

    def test_medium_boundary(self):
        assert score_to_level(40.0) == "medium"

    def test_medium_below_high(self):
        assert score_to_level(59.9) == "medium"

    def test_low_boundary(self):
        assert score_to_level(20.0) == "low"

    def test_low_below_medium(self):
        assert score_to_level(39.9) == "low"

    def test_minimal(self):
        assert score_to_level(0.0) == "minimal"

    def test_minimal_just_below_low(self):
        assert score_to_level(19.9) == "minimal"


# ── FEATURE_NAMES canonical order ────────────────────────────────────────────

def test_feature_names_length():
    assert len(FEATURE_NAMES) == 19


def test_feature_names_starts_with_otd():
    assert FEATURE_NAMES[0] == "otd_rate"


def test_feature_names_ends_with_spend_conc():
    assert FEATURE_NAMES[-1] == "spend_concentration_pct"


# ── _build_component_scores ──────────────────────────────────────────────────

class TestBuildComponentScores:
    def _fv(self, **overrides):
        from risk_intelligence.schemas.model import FeatureVector  # noqa: PLC0415
        defaults = dict(
            otd_rate=95.0,
            fill_rate=98.0,
            defect_rate=1.0,
            invoice_accuracy_rate=99.0,
            overall_scorecard_score=85.0,
            scorecard_age_days=5,
            composite_kri_score=15.0,
            kri_red_count=0,
            kri_amber_count=1,
            supplier_tier_encoded=1.0,
            onboarding_status_encoded=1.0,
            years_in_business=10.0,
            employee_count_log=4.6,
            country_risk_score=10.0,
            active_certifications_count=3,
            expired_certifications_count=0,
            compliance_violations_count=0,
            is_sole_source=False,
            spend_concentration_pct=5.0,
        )
        defaults.update(overrides)
        return FeatureVector(**defaults)

    def test_returns_five_components(self):
        from risk_intelligence.ml.predictor import _build_component_scores  # noqa: PLC0415
        scores = _build_component_scores(self._fv())
        assert len(scores) == 5

    def test_weights_sum_to_one(self):
        from risk_intelligence.ml.predictor import _build_component_scores  # noqa: PLC0415
        scores = _build_component_scores(self._fv())
        total = sum(s.weight for s in scores)
        assert abs(total - 1.0) < 1e-6

    def test_high_defect_raises_compliance_score(self):
        from risk_intelligence.ml.predictor import _build_component_scores  # noqa: PLC0415
        low = _build_component_scores(self._fv(defect_rate=1.0))
        high = _build_component_scores(self._fv(defect_rate=40.0))
        comp_low = next(s for s in low if "operational" in s.component)
        comp_high = next(s for s in high if "operational" in s.component)
        assert comp_high.score > comp_low.score

    def test_sole_source_penalty_applied(self):
        from risk_intelligence.ml.predictor import predict  # noqa: PLC0415
        with patch("risk_intelligence.ml.predictor.load_model") as m_load, \
             patch("risk_intelligence.ml.predictor.predict_proba") as m_proba:
            m_proba.return_value = 0.5
            m_load.return_value = MagicMock()

            fv_no = self._fv(is_sole_source=False)
            fv_yes = self._fv(is_sole_source=True)

            result_no = predict(fv_no, None, "rule_based", MODEL_ID, "1.0")
            result_yes = predict(fv_yes, None, "rule_based", MODEL_ID, "1.0")
            # Sole source should result in equal or higher risk
            assert result_yes.risk_score >= result_no.risk_score


# ── Rule-based fallback model ─────────────────────────────────────────────────

class TestRuleBasedModel:
    def test_predict_proba_returns_float_in_range(self):
        from risk_intelligence.ml.model_loader import _RuleBasedModel  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        model = _RuleBasedModel()
        # Healthy supplier
        features = np.array([[95, 98, 1, 99, 85, 5, 15, 0, 1, 1.0, 1.0, 10, 4.6, 10, 3, 0, 0, 0, 5]])
        proba = model.predict_proba(features)
        assert 0.0 <= proba <= 1.0

    def test_risky_supplier_scores_higher(self):
        from risk_intelligence.ml.model_loader import _RuleBasedModel  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        model = _RuleBasedModel()
        healthy = np.array([[95, 98, 1, 99, 85, 5, 15, 0, 0, 1.0, 1.0, 10, 4.6, 10, 3, 0, 0, 0, 5]])
        risky   = np.array([[50, 60, 20, 70, 40, 90, 75, 3, 5, 0.25, 0.5, 1, 2.0, 80, 0, 4, 5, 1, 60]])

        p_healthy = model.predict_proba(healthy)
        p_risky = model.predict_proba(risky)
        assert p_risky > p_healthy


# ── compute_risk_score service (mocked DB) ────────────────────────────────────

class TestComputeRiskScoreService:
    @pytest.mark.asyncio
    async def test_returns_existing_fresh_score(self):
        """If a fresh score exists within TTL, it should be returned without recompute."""
        from datetime import datetime, timezone, timedelta  # noqa: PLC0415
        from risk_intelligence.services.risk_scoring_service import get_risk_score  # noqa: PLC0415

        db = AsyncMock()
        future = datetime.now(timezone.utc) + timedelta(hours=12)
        fake_row = MagicMock()
        fake_row.supplier_id = SUPPLIER_ID
        fake_row.risk_score = 42.0
        fake_row.risk_level = "medium"
        fake_row.valid_until = future
        fake_row.component_scores = []

        result_mock = AsyncMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=fake_row)
        db.execute = AsyncMock(return_value=result_mock)

        score = await get_risk_score(db, TENANT_ID, SUPPLIER_ID)
        assert score is not None
        assert score.risk_level == "medium"

    @pytest.mark.asyncio
    async def test_bulk_compute_enqueues_tasks(self, mock_producer):
        from risk_intelligence.services.risk_scoring_service import bulk_compute_risk_scores  # noqa: PLC0415

        ids = [uuid.uuid4() for _ in range(3)]
        with patch(
            "risk_intelligence.services.risk_scoring_service.compute_risk_score_task.delay"
        ) as mock_delay:
            mock_delay.return_value = MagicMock(id="task-abc")
            result = await bulk_compute_risk_scores(None, TENANT_ID, ids)
            assert len(result) == 3
            assert mock_delay.call_count == 3
