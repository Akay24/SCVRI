"""Unit tests for KRI thresholds, snapshot recording, and dashboard aggregation."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TENANT_ID, SUPPLIER_ID, KRI_DEFINITION_ID, USER_ID


# ── _evaluate_threshold ───────────────────────────────────────────────────────

class TestEvaluateThreshold:
    def _kri(self, green_threshold: float, amber_threshold: float, is_inverted: bool) -> dict:
        return {
            "green_threshold": green_threshold,
            "amber_threshold": amber_threshold,
            "is_inverted": is_inverted,
        }

    def _eval(self, value: float, green: float, amber: float, inverted: bool) -> str:
        from risk_intelligence.services.kri_service import _evaluate_threshold  # noqa: PLC0415
        return _evaluate_threshold(value, self._kri(green, amber, inverted))

    # Non-inverted: higher value = worse
    def test_non_inverted_green(self):
        # value <= green_threshold → green
        assert self._eval(50.0, green_threshold=80.0, amber=60.0, inverted=False) == "green"

    def test_non_inverted_amber(self):
        # amber_threshold < value <= green_threshold
        assert self._eval(70.0, green_threshold=80.0, amber=60.0, inverted=False) == "amber"

    def test_non_inverted_red(self):
        # value > green_threshold → red
        assert self._eval(85.0, green_threshold=80.0, amber=60.0, inverted=False) == "red"

    def test_non_inverted_exactly_green_threshold(self):
        assert self._eval(80.0, green_threshold=80.0, amber=60.0, inverted=False) in {"green", "amber"}

    # Inverted: lower value = worse (e.g. OTD rate — low is bad)
    def test_inverted_red_below_amber_threshold(self):
        # value <= amber_threshold → red
        assert self._eval(40.0, green_threshold=90.0, amber=60.0, inverted=True) == "red"

    def test_inverted_amber(self):
        # amber < value <= green
        assert self._eval(75.0, green_threshold=90.0, amber=60.0, inverted=True) == "amber"

    def test_inverted_green(self):
        # value > green_threshold → green
        assert self._eval(95.0, green_threshold=90.0, amber=60.0, inverted=True) == "green"


# ── threshold breach detection ────────────────────────────────────────────────

class TestThresholdBreachDetection:
    @pytest.mark.asyncio
    async def test_worsening_emits_kafka_event(self, mock_producer):
        """A status change from green to amber should emit a kri.threshold.breached event."""
        from risk_intelligence.services.kri_service import record_kri_snapshot  # noqa: PLC0415
        from risk_intelligence.schemas.kri import KRISnapshotCreate  # noqa: PLC0415

        db = AsyncMock()

        # Previous snapshot = green
        prev_snap = MagicMock()
        prev_snap.status = "green"
        prev_snap.value = 85.0

        # KRI definition
        kri_def = MagicMock()
        kri_def.id = KRI_DEFINITION_ID
        kri_def.green_threshold = 80.0
        kri_def.amber_threshold = 60.0
        kri_def.is_inverted = False
        kri_def.weight = 1.0
        kri_def.name = "Test KRI"
        kri_def.category = "operational"

        # Mock DB responses for get definition + get previous snapshot
        execute_call_count = 0
        def side_effect(q, *a, **kw):
            nonlocal execute_call_count
            execute_call_count += 1
            r = AsyncMock()
            if execute_call_count == 1:
                r.scalar_one_or_none = MagicMock(return_value=kri_def)
            else:
                r.scalar_one_or_none = MagicMock(return_value=prev_snap)
            return r

        db.execute = AsyncMock(side_effect=side_effect)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        snap_in = KRISnapshotCreate(
            supplier_id=SUPPLIER_ID,
            kri_definition_id=KRI_DEFINITION_ID,
            value=70.0,  # amber range → worsened from green
        )

        with patch("risk_intelligence.services.kri_service.get_producer") as mock_gp:
            producer = AsyncMock()
            producer.send = AsyncMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=producer)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = cm

            snap_out = await record_kri_snapshot(db, TENANT_ID, USER_ID, snap_in)

        producer.send.assert_called_once()
        call_kwargs = producer.send.call_args
        topic = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("topic")
        assert topic == "risk.events"

    @pytest.mark.asyncio
    async def test_stable_status_no_kafka_event(self, mock_producer):
        """When the status has not worsened, no Kafka event should be emitted."""
        from risk_intelligence.services.kri_service import record_kri_snapshot  # noqa: PLC0415
        from risk_intelligence.schemas.kri import KRISnapshotCreate  # noqa: PLC0415

        db = AsyncMock()

        # Previous snapshot = amber
        prev_snap = MagicMock()
        prev_snap.status = "amber"
        prev_snap.value = 70.0

        kri_def = MagicMock()
        kri_def.id = KRI_DEFINITION_ID
        kri_def.green_threshold = 80.0
        kri_def.amber_threshold = 60.0
        kri_def.is_inverted = False
        kri_def.weight = 1.0
        kri_def.name = "Test KRI"
        kri_def.category = "operational"

        execute_call_count = 0
        def side_effect(q, *a, **kw):
            nonlocal execute_call_count
            execute_call_count += 1
            r = AsyncMock()
            if execute_call_count == 1:
                r.scalar_one_or_none = MagicMock(return_value=kri_def)
            else:
                r.scalar_one_or_none = MagicMock(return_value=prev_snap)
            return r

        db.execute = AsyncMock(side_effect=side_effect)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        snap_in = KRISnapshotCreate(
            supplier_id=SUPPLIER_ID,
            kri_definition_id=KRI_DEFINITION_ID,
            value=72.0,  # still amber → no worsening
        )

        with patch("risk_intelligence.services.kri_service.get_producer") as mock_gp:
            producer = AsyncMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=producer)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = cm

            await record_kri_snapshot(db, TENANT_ID, USER_ID, snap_in)

        producer.send.assert_not_called()


# ── KRI dashboard aggregation ─────────────────────────────────────────────────

class TestSupplierKRIDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_returns_rag_counts(self):
        from risk_intelligence.services.kri_service import get_supplier_kri_dashboard  # noqa: PLC0415

        db = AsyncMock()
        fake_rows = [
            MagicMock(status="green"),
            MagicMock(status="green"),
            MagicMock(status="amber"),
            MagicMock(status="red"),
        ]
        result_mock = AsyncMock()
        result_mock.mappings = MagicMock(return_value=AsyncMock(
            __aiter__=lambda s: iter(fake_rows),
            all=MagicMock(return_value=fake_rows)
        ))
        db.execute = AsyncMock(return_value=result_mock)

        dashboard = await get_supplier_kri_dashboard(db, TENANT_ID, SUPPLIER_ID)

        assert dashboard.green_count == 2
        assert dashboard.amber_count == 1
        assert dashboard.red_count == 1
        # composite = (1*1 + 2*amber + 3*red) / total_weight (varies by weights)
        assert 0.0 <= dashboard.composite_kri_score <= 100.0
