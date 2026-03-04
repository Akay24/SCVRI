"""Unit tests for shipment tracking and telemetry service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from visibility.schemas.shipment import GeoCoordinate
from tests.conftest import TENANT_ID, USER_ID, SUPPLIER_ID, SHIPMENT_ID


# ── GeoCoordinate validation ──────────────────────────────────────────────────

class TestGeoCoordinate:
    def test_valid_coords(self):
        coord = GeoCoordinate(latitude=51.5074, longitude=-0.1278)
        assert coord.latitude == 51.5074

    def test_latitude_out_of_range(self):
        from pydantic import ValidationError  # noqa: PLC0415
        with pytest.raises(ValidationError):
            GeoCoordinate(latitude=91.0, longitude=0.0)

    def test_longitude_out_of_range(self):
        from pydantic import ValidationError  # noqa: PLC0415
        with pytest.raises(ValidationError):
            GeoCoordinate(latitude=0.0, longitude=200.0)


# ── Tracking event → status mapping ──────────────────────────────────────────

class TestEventToStatus:
    def test_picked_up(self):
        from visibility.services.shipment_service import _event_to_status  # noqa: PLC0415
        assert _event_to_status("picked_up") == "picked_up"

    def test_delivered(self):
        from visibility.services.shipment_service import _event_to_status  # noqa: PLC0415
        assert _event_to_status("delivered") == "delivered"

    def test_customs_hold(self):
        from visibility.services.shipment_service import _event_to_status  # noqa: PLC0415
        assert _event_to_status("customs_hold") == "customs_hold"

    def test_unknown_defaults_to_in_transit(self):
        from visibility.services.shipment_service import _event_to_status  # noqa: PLC0415
        assert _event_to_status("some_unknown_event") == "in_transit"


# ── Shipment schema validation ─────────────────────────────────────────────────

class TestShipmentSchema:
    def test_valid_shipment_create(self):
        from visibility.schemas.shipment import ShipmentCreate  # noqa: PLC0415
        s = ShipmentCreate(
            po_id=uuid.uuid4(),
            carrier="Maersk",
            carrier_type="ocean",
            tracking_number="MAEU1234567",
            origin_address="Shanghai Port, China",
            destination_address="Port of Felixstowe, UK",
        )
        assert s.carrier_type == "ocean"


# ── ETA prediction — already delivered ───────────────────────────────────────

class TestETAPrediction:
    @pytest.mark.asyncio
    async def test_delivered_ship_returns_actual_arrival(self):
        from visibility.services.shipment_service import predict_eta  # noqa: PLC0415
        from visibility.schemas.shipment import ShipmentResponse  # noqa: PLC0415

        now = datetime.now(timezone.utc)
        fake_shipment = MagicMock(spec=ShipmentResponse)
        fake_shipment.actual_arrival = now
        fake_shipment.estimated_arrival = now
        fake_shipment.carrier_type = "ocean"
        fake_shipment.status = "delivered"

        db = AsyncMock()

        with patch("visibility.services.shipment_service.get_shipment", return_value=fake_shipment):
            result = await predict_eta(db, TENANT_ID, SHIPMENT_ID)

        assert result.predicted_arrival == now
        assert result.delay_risk == "low"

    @pytest.mark.asyncio
    async def test_in_transit_customs_hold_risk(self):
        from visibility.services.shipment_service import predict_eta  # noqa: PLC0415
        from visibility.schemas.shipment import ShipmentResponse  # noqa: PLC0415
        from datetime import timedelta  # noqa: PLC0415

        now = datetime.now(timezone.utc)
        fake_shipment = MagicMock(spec=ShipmentResponse)
        fake_shipment.actual_arrival = None
        fake_shipment.estimated_arrival = now + timedelta(days=2)
        fake_shipment.carrier_type = "ocean"
        fake_shipment.status = "customs_hold"

        db = AsyncMock()
        result_mock = AsyncMock()
        result_mock.scalar = MagicMock(return_value=None)  # no history → defaults to 14d
        db.execute = AsyncMock(return_value=result_mock)

        with patch("visibility.services.shipment_service.get_shipment", return_value=fake_shipment):
            result = await predict_eta(db, TENANT_ID, SHIPMENT_ID)

        assert result.delay_risk == "high"
        assert any("customs_hold" in f for f in result.delay_factors)


# ── Geofence – bbox evaluation ────────────────────────────────────────────────

class TestGeofenceBoundingBox:
    @pytest.mark.asyncio
    async def test_point_inside_bbox_emits_enter_event(self, mock_producer):
        from visibility.services.telemetry_service import _evaluate_geofence  # noqa: PLC0415
        from visibility.schemas.telemetry import TelemetryPayload  # noqa: PLC0415

        db = AsyncMock()

        fence_row = {
            "id": str(uuid.uuid4()),
            "name": "Port Zone",
            "min_lat": 50.0,
            "max_lat": 52.0,
            "min_lon": -1.0,
            "max_lon": 1.0,
            "wkt_polygon": None,
        }
        result_mock = AsyncMock()
        result_mock.mappings = MagicMock(return_value=AsyncMock(all=MagicMock(return_value=[fence_row])))
        db.execute = AsyncMock(return_value=result_mock)

        payload = TelemetryPayload(
            device_id="DEV-001",
            shipment_id=SHIPMENT_ID,
            tenant_id=TENANT_ID,
            event_type="location_update",
            occurred_at=datetime.now(timezone.utc),
            latitude=51.0,
            longitude=0.5,
        )

        with patch("visibility.services.telemetry_service.get_producer") as mock_gp:
            producer = AsyncMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=producer)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = cm

            geo_id, geo_name = await _evaluate_geofence(db, TENANT_ID, payload, None, None)

        assert geo_name == "Port Zone"
        producer.send.assert_called_once()
        args = producer.send.call_args
        assert "geofence_enter" in (args[1].get("event_type") or args[0][1])

    @pytest.mark.asyncio
    async def test_point_outside_bbox_no_event(self, mock_producer):
        from visibility.services.telemetry_service import _evaluate_geofence  # noqa: PLC0415
        from visibility.schemas.telemetry import TelemetryPayload  # noqa: PLC0415

        db = AsyncMock()

        fence_row = {
            "id": str(uuid.uuid4()),
            "name": "Port Zone",
            "min_lat": 50.0,
            "max_lat": 52.0,
            "min_lon": -1.0,
            "max_lon": 1.0,
            "wkt_polygon": None,
        }
        result_mock = AsyncMock()
        result_mock.mappings = MagicMock(return_value=AsyncMock(all=MagicMock(return_value=[fence_row])))
        db.execute = AsyncMock(return_value=result_mock)

        payload = TelemetryPayload(
            device_id="DEV-001",
            shipment_id=SHIPMENT_ID,
            tenant_id=TENANT_ID,
            event_type="location_update",
            occurred_at=datetime.now(timezone.utc),
            latitude=53.0,   # outside the bbox
            longitude=0.5,
        )

        with patch("visibility.services.telemetry_service.get_producer") as mock_gp:
            producer = AsyncMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=producer)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = cm

            geo_id, geo_name = await _evaluate_geofence(db, TENANT_ID, payload, None, None)

        assert geo_id is None
        assert geo_name is None
        producer.send.assert_not_called()


# ── Telemetry alert thresholds ────────────────────────────────────────────────

class TestTelemetryAlerts:
    @pytest.mark.asyncio
    async def test_temperature_breach_sets_alert_flag(self, mock_producer):
        from visibility.services.telemetry_service import process_telemetry  # noqa: PLC0415
        from visibility.schemas.telemetry import TelemetryPayload  # noqa: PLC0415

        db = AsyncMock()
        db.execute = AsyncMock(return_value=AsyncMock())
        db.commit = AsyncMock()

        payload = TelemetryPayload(
            device_id="TEMP-001",
            shipment_id=SHIPMENT_ID,
            tenant_id=TENANT_ID,
            event_type="temperature_breach",
            occurred_at=datetime.now(timezone.utc),
            temperature_c=45.0,   # above threshold
        )

        with patch("visibility.services.telemetry_service.get_producer") as mock_gp, \
             patch("visibility.services.telemetry_service._evaluate_geofence",
                   return_value=(None, None)):
            producer = AsyncMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=producer)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = cm

            result = await process_telemetry(db, TENANT_ID, payload)

        assert result.alert_triggered is True
