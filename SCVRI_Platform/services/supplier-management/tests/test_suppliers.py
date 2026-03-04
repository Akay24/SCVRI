"""Tests for supplier CRUD, search, bulk ops, and onboarding state machine.

Uses mocked DB layer via service-layer patches so that no real PostgreSQL
connection is required in CI.  Integration tests (against real DB) live
in tests/integration/.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_SUPPLIER_ID = uuid.uuid4()
_TENANT_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_supplier(**kwargs) -> MagicMock:
    s = MagicMock()
    s.id = kwargs.get("id", _SUPPLIER_ID)
    s.tenant_id = _TENANT_ID
    s.name = kwargs.get("name", "Acme Corp")
    s.legal_name = kwargs.get("legal_name", "Acme Corporation Ltd")
    s.tax_id = "12-3456789"
    s.country_code = "US"
    s.industry_code = "MFG"
    s.employee_count = 500
    s.annual_revenue_usd = 50_000_000
    s.currency_code = "USD"
    s.supplier_tier = "tier_1"
    s.onboarding_status = "draft"
    s.status = "pending"
    s.tags = []
    s.diversity_info = None
    s.custom_fields = {}
    s.website = None
    s.address = None
    s.deleted_at = None
    s.created_at = None
    s.updated_at = None
    s.search_tsv = None
    return s


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------
class TestSupplierCreateSchema:
    def test_valid_creation(self):
        from supplier_management.schemas.supplier import SupplierCreate  # noqa: PLC0415

        data = SupplierCreate(
            name="Test Corp",
            legal_name="Test Corporation Inc.",
            country_code="de",  # lowercase — should be uppercased
            industry_code="MFG",
            supplier_tier="tier_2",
        )
        assert data.country_code == "DE"

    def test_invalid_tier(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from supplier_management.schemas.supplier import SupplierCreate  # noqa: PLC0415

        with pytest.raises(ValidationError):
            SupplierCreate(
                name="X",
                legal_name="X Corp",
                country_code="US",
                industry_code="MFG",
                supplier_tier="tier_99",  # invalid
            )

    def test_country_code_uppercase(self):
        from supplier_management.schemas.supplier import SupplierCreate  # noqa: PLC0415

        data = SupplierCreate(
            name="Supplier",
            legal_name="Supplier Ltd",
            country_code="gb",
            industry_code="RET",
            supplier_tier="tier_1",
        )
        assert data.country_code == "GB"


# ---------------------------------------------------------------------------
# Service layer unit tests (mocked DB)
# ---------------------------------------------------------------------------
class TestSupplierService:
    @pytest.mark.asyncio
    async def test_get_supplier_not_found(self):
        from scvri_shared.exceptions import NotFoundError  # noqa: PLC0415
        from supplier_management.services import supplier_service  # noqa: PLC0415

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await supplier_service.get_supplier(mock_db, _TENANT_ID, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_supplier_soft_deleted_raises_not_found(self):
        from scvri_shared.exceptions import NotFoundError  # noqa: PLC0415
        from supplier_management.services import supplier_service  # noqa: PLC0415
        from datetime import datetime, timezone  # noqa: PLC0415

        deleted = _make_supplier()
        deleted.deleted_at = datetime.now(tz=timezone.utc)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = deleted
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await supplier_service.get_supplier(mock_db, _TENANT_ID, _SUPPLIER_ID)

    @pytest.mark.asyncio
    async def test_transition_invalid_raises_state_error(self):
        from scvri_shared.exceptions import StateTransitionError  # noqa: PLC0415
        from supplier_management.services import supplier_service  # noqa: PLC0415
        from supplier_management.schemas.supplier import OnboardingTransitionRequest  # noqa: PLC0415

        supplier = _make_supplier()
        supplier.onboarding_status = "approved"  # approved → submitted is invalid

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = supplier
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = OnboardingTransitionRequest(
            target_status="submitted",
            reason="test",
        )

        with pytest.raises(StateTransitionError):
            await supplier_service.transition_onboarding(
                mock_db, _TENANT_ID, _SUPPLIER_ID, _USER_ID, req
            )

    @pytest.mark.asyncio
    async def test_bulk_update_status_returns_count(self):
        from supplier_management.services import supplier_service  # noqa: PLC0415
        from supplier_management.schemas.supplier import BulkSupplierStatusUpdate  # noqa: PLC0415

        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ids
        mock_db.execute = AsyncMock(return_value=mock_result)

        data = BulkSupplierStatusUpdate(supplier_ids=ids, status="inactive")

        with patch("supplier_management.services.supplier_service.get_producer") as mock_gp:
            fake_producer = AsyncMock()
            fake_producer.publish = AsyncMock()
            mock_gp.return_value.__aenter__ = AsyncMock(return_value=fake_producer)
            mock_gp.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await supplier_service.bulk_update_status(
                mock_db, _TENANT_ID, _USER_ID, data
            )

        assert count == 3

    def test_onboarding_fsm_completeness(self):
        """Every terminal state must be present; every allowed transition must be a key."""
        from supplier_management.services.supplier_service import _ONBOARDING_FSM  # noqa: PLC0415

        all_states = set(_ONBOARDING_FSM.keys())
        for _from, transitions in _ONBOARDING_FSM.items():
            for to in transitions:
                assert to in all_states, f"Transition target '{to}' is not a valid state"

        # terminal states have empty sets
        assert _ONBOARDING_FSM["rejected"] == set()
        assert _ONBOARDING_FSM["inactive"] == set()


# ---------------------------------------------------------------------------
# Scorecard schema validation
# ---------------------------------------------------------------------------
class TestScorecardSchema:
    def test_on_time_cannot_exceed_total(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from supplier_management.schemas.scorecard import ScorecardCreate  # noqa: PLC0415
        from datetime import date  # noqa: PLC0415

        with pytest.raises(ValidationError, match="on_time_deliveries"):
            ScorecardCreate(
                period_start=date(2024, 1, 1),
                period_end=date(2024, 3, 31),
                total_deliveries=10,
                on_time_deliveries=15,  # > total ❌
                quantity_ordered=100,
                quantity_received=90,
                quantity_returned=5,
            )

    def test_received_cannot_exceed_ordered(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from supplier_management.schemas.scorecard import ScorecardCreate  # noqa: PLC0415
        from datetime import date  # noqa: PLC0415

        with pytest.raises(ValidationError):
            ScorecardCreate(
                period_start=date(2024, 1, 1),
                period_end=date(2024, 3, 31),
                total_deliveries=10,
                on_time_deliveries=8,
                quantity_ordered=100,
                quantity_received=110,  # > ordered ❌
                quantity_returned=0,
            )


# ---------------------------------------------------------------------------
# Scorecard service unit tests
# ---------------------------------------------------------------------------
class TestScorecardService:
    def test_compute_overall_perfect_score(self):
        from supplier_management.services.scorecard_service import _compute_overall  # noqa: PLC0415
        score = _compute_overall(100.0, 100.0, 0.0, 100.0)
        assert score == 100.0

    def test_compute_overall_zero_score(self):
        from supplier_management.services.scorecard_service import _compute_overall  # noqa: PLC0415
        score = _compute_overall(0.0, 0.0, 100.0, 0.0)
        # 0*0.35 + 0*0.25 + (100-100)*0.25 + 0*0.15 = 0
        assert score == 0.0

    def test_grade_boundaries(self):
        from supplier_management.services.scorecard_service import _compute_grade  # noqa: PLC0415
        assert _compute_grade(85.0) == "A"
        assert _compute_grade(84.9) == "B"
        assert _compute_grade(70.0) == "B"
        assert _compute_grade(69.9) == "C"
        assert _compute_grade(55.0) == "C"
        assert _compute_grade(54.9) == "D"

    def test_safe_rate_zero_denominator(self):
        from supplier_management.services.scorecard_service import _safe_rate  # noqa: PLC0415
        assert _safe_rate(10, 0) == 0.0
