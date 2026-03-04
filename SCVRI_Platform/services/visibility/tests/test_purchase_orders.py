"""Unit tests for the Purchase Order state machine and service layer."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

import pytest

from visibility.schemas.purchase_order import (
    PO_TRANSITIONS,
    TERMINAL_PO_STATUSES,
)
from tests.conftest import TENANT_ID, USER_ID, SUPPLIER_ID, PO_ID


# ── State machine transitions ─────────────────────────────────────────────────

class TestPOStateMachine:
    def test_draft_confirm(self):
        assert PO_TRANSITIONS[("draft", "confirm")] == "confirmed"

    def test_confirmed_ship_partial(self):
        assert PO_TRANSITIONS[("confirmed", "ship_partial")] == "partially_shipped"

    def test_confirmed_ship_complete(self):
        assert PO_TRANSITIONS[("confirmed", "ship_complete")] == "shipped"

    def test_shipped_receive_complete(self):
        assert PO_TRANSITIONS[("shipped", "receive_complete")] == "received"

    def test_shipped_dispute(self):
        assert PO_TRANSITIONS[("shipped", "dispute")] == "disputed"

    def test_disputed_resolve(self):
        assert PO_TRANSITIONS[("disputed", "resolve")] == "received"

    def test_draft_cancel(self):
        assert PO_TRANSITIONS[("draft", "cancel")] == "cancelled"

    def test_invalid_transition_returns_none(self):
        assert PO_TRANSITIONS.get(("received", "confirm")) is None

    def test_terminal_statuses(self):
        assert "received" in TERMINAL_PO_STATUSES
        assert "cancelled" in TERMINAL_PO_STATUSES

    def test_all_transition_targets_are_valid_statuses(self):
        valid = {
            "draft", "confirmed", "partially_shipped", "shipped",
            "partially_received", "received", "cancelled", "disputed",
        }
        for _src, target in PO_TRANSITIONS.items():
            assert target in valid, f"Invalid target status: {target}"


# ── PO schema validation ──────────────────────────────────────────────────────

class TestPurchaseOrderSchema:
    def _line(self, **overrides):
        from visibility.schemas.purchase_order import POLineCreate  # noqa: PLC0415
        defaults = dict(
            line_number=1,
            product_code="SKU-001",
            product_description="Test Product",
            quantity_ordered=100.0,
            unit_of_measure="EA",
            unit_price=9.99,
        )
        defaults.update(overrides)
        return POLineCreate(**defaults)

    def test_valid_po(self):
        from visibility.schemas.purchase_order import PurchaseOrderCreate  # noqa: PLC0415
        po = PurchaseOrderCreate(
            supplier_id=SUPPLIER_ID,
            po_number="PO-2026-001",
            lines=[self._line()],
        )
        assert po.po_number == "PO-2026-001"

    def test_po_number_uppercased(self):
        from visibility.schemas.purchase_order import PurchaseOrderCreate  # noqa: PLC0415
        po = PurchaseOrderCreate(
            supplier_id=SUPPLIER_ID,
            po_number="po-2026-001",
            lines=[self._line()],
        )
        assert po.po_number == "PO-2026-001"

    def test_empty_lines_raises(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from visibility.schemas.purchase_order import PurchaseOrderCreate  # noqa: PLC0415
        with pytest.raises(ValidationError):
            PurchaseOrderCreate(supplier_id=SUPPLIER_ID, po_number="PO-X", lines=[])

    def test_blank_po_number_raises(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from visibility.schemas.purchase_order import PurchaseOrderCreate  # noqa: PLC0415
        with pytest.raises(ValidationError):
            PurchaseOrderCreate(supplier_id=SUPPLIER_ID, po_number="   ", lines=[self._line()])

    def test_line_shipment_positive_quantity(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from visibility.schemas.purchase_order import POLineShipment  # noqa: PLC0415
        with pytest.raises(ValidationError):
            POLineShipment(line_id=uuid.uuid4(), quantity=-1.0)


# ── PO service — apply_po_event ───────────────────────────────────────────────

class TestApplyPOEvent:
    def _mock_po(self, status: str):
        from visibility.schemas.purchase_order import PurchaseOrderResponse  # noqa: PLC0415
        po = MagicMock(spec=PurchaseOrderResponse)
        po.status = status
        po.supplier_id = SUPPLIER_ID
        po.id = PO_ID
        return po

    @pytest.mark.asyncio
    async def test_valid_transition_succeeds(self, mock_producer):
        from visibility.services.po_service import apply_po_event  # noqa: PLC0415
        from visibility.schemas.purchase_order import POEventRequest  # noqa: PLC0415

        db = AsyncMock()
        db.execute = AsyncMock(return_value=AsyncMock())
        db.commit = AsyncMock()

        with patch(
            "visibility.services.po_service.get_purchase_order",
            side_effect=[self._mock_po("draft"), self._mock_po("confirmed")],
        ), patch("visibility.services.po_service.get_producer") as mock_gp:
            producer = AsyncMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=producer)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = cm

            result = await apply_po_event(
                db, TENANT_ID, USER_ID, PO_ID,
                POEventRequest(event="confirm"),
            )

        assert result.status == "confirmed"
        producer.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, mock_producer):
        from visibility.services.po_service import apply_po_event  # noqa: PLC0415
        from visibility.schemas.purchase_order import POEventRequest  # noqa: PLC0415
        from scvri_shared.exceptions import BusinessRuleError  # noqa: PLC0415

        db = AsyncMock()

        with patch(
            "visibility.services.po_service.get_purchase_order",
            return_value=self._mock_po("received"),
        ):
            with pytest.raises(BusinessRuleError):
                await apply_po_event(
                    db, TENANT_ID, USER_ID, PO_ID,
                    POEventRequest(event="confirm"),
                )


# ── Delivery metrics ──────────────────────────────────────────────────────────

class TestDeliveryMetrics:
    @pytest.mark.asyncio
    async def test_otd_rate_calculation(self):
        from visibility.services.po_service import get_delivery_metrics  # noqa: PLC0415

        db = AsyncMock()
        fake_row = {
            "total": 10,
            "on_time": 8,
            "late": 2,
            "avg_days_late": 1.5,
            "avg_lead_time": 12.0,
        }
        result_mock = AsyncMock()
        result_mock.mappings = MagicMock(return_value=AsyncMock(
            one=MagicMock(return_value=fake_row)
        ))
        db.execute = AsyncMock(return_value=result_mock)

        now = datetime.now(timezone.utc)
        metrics = await get_delivery_metrics(
            db, TENANT_ID, SUPPLIER_ID,
            now - timedelta(days=30),
            now,
        )

        assert metrics.otd_rate == 80.0
        assert metrics.total_pos == 10
        assert metrics.on_time_count == 8
