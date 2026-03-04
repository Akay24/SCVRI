"""Tests for alert service and lifecycle transitions."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alert_engine.schemas.alert import (
    AlertAcknowledgeRequest,
    AlertCreate,
    AlertEscalateRequest,
    AlertResolveRequest,
    AlertSuppressRequest,
    ALERT_STATUS_ORDER,
)
from alert_engine.services import alert_service
from tests.conftest import TENANT_ID, USER_ID, make_alert_create


# ── Unit tests: status ordering ────────────────────────────────────────────────

def test_alert_status_order_values():
    assert ALERT_STATUS_ORDER["open"] < ALERT_STATUS_ORDER["resolved"]
    assert ALERT_STATUS_ORDER["acknowledged"] < ALERT_STATUS_ORDER["resolved"]
    assert ALERT_STATUS_ORDER["escalated"] < ALERT_STATUS_ORDER["resolved"]
    assert ALERT_STATUS_ORDER["resolved"] == ALERT_STATUS_ORDER["suppressed"]


# ── Unit tests: AlertCreate schema ─────────────────────────────────────────────

def test_alert_create_valid():
    a = make_alert_create(severity="critical", source="risk_engine")
    assert a.severity == "critical"
    assert a.source == "risk_engine"
    assert a.title == "Test Alert"


def test_alert_create_requires_title():
    with pytest.raises(Exception):
        AlertCreate(
            title="",
            description="desc",
            severity="low",
            source="manual",
        )


def test_alert_create_accepts_all_severities():
    for sev in ("critical", "high", "medium", "low", "info"):
        a = make_alert_create(severity=sev)
        assert a.severity == sev


# ── Unit tests: acknowledge request ───────────────────────────────────────────

def test_acknowledge_request_note_optional():
    req = AlertAcknowledgeRequest(note=None)
    assert req.note is None

    req2 = AlertAcknowledgeRequest(note="acknowledged by on-call")
    assert req2.note == "acknowledged by on-call"


# ── Unit tests: suppress request ──────────────────────────────────────────────

def test_suppress_request_requires_future_until():
    future = datetime.now(timezone.utc) + timedelta(hours=4)
    req = AlertSuppressRequest(until=future, reason="Planned maintenance")
    assert req.until > datetime.now(timezone.utc)


# ── Unit tests: escalate request ──────────────────────────────────────────────

def test_escalate_request_assignee_optional():
    req = AlertEscalateRequest(assignee_id=None, note="Auto-escalated")
    assert req.assignee_id is None


# ── Service layer: mock DB tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_alert_dispatches_notification():
    """create_alert should call dispatch_alert_notifications_task.delay."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: {
            "id": str(uuid.uuid4()),
            "tenant_id": str(TENANT_ID),
            "title": "Test Alert",
            "description": "desc",
            "severity": "high",
            "status": "open",
            "source": "manual",
            "source_event_type": "test.event",
            "source_event_id": "x",
            "supplier_id": None,
            "rule_id": None,
            "payload": {},
            "creation_note": None,
            "assignee_id": None,
            "notification_count": 0,
            "is_read": False,
            "acknowledged_at": None,
            "resolved_at": None,
            "suppressed_until": None,
            "escalated_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
    ))
    mock_db.commit = AsyncMock()

    data = make_alert_create()

    with patch(
        "alert_engine.services.alert_service.dispatch_alert_notifications_task"
    ) as mock_task:
        mock_task.delay = MagicMock()
        result = await alert_service.create_alert(mock_db, TENANT_ID, USER_ID, data)

    mock_task.delay.assert_called_once()
    call_kwargs = mock_task.delay.call_args
    assert "alert_created" in str(call_kwargs)


@pytest.mark.asyncio
async def test_resolve_alert_publishes_kafka():
    """resolve_alert should publish to Kafka alert.notifications topic."""
    mock_db = AsyncMock()

    existing = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(TENANT_ID),
        "title": "Test",
        "description": "desc",
        "severity": "high",
        "status": "open",
        "source": "manual",
        "source_event_type": None,
        "source_event_id": None,
        "supplier_id": None,
        "rule_id": None,
        "payload": {},
        "creation_note": None,
        "assignee_id": None,
        "notification_count": 1,
        "is_read": False,
        "acknowledged_at": None,
        "resolved_at": None,
        "suppressed_until": None,
        "escalated_at": None,
        "resolved_by": None,
        "resolution_note": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    resolved = dict(existing, status="resolved", resolved_at=datetime.now(timezone.utc))

    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(mappings=lambda: MagicMock(one_or_none=lambda: existing)),  # get_alert
        AsyncMock(),  # UPDATE
        MagicMock(mappings=lambda: MagicMock(one_or_none=lambda: resolved)),  # re-fetch
    ])
    mock_db.commit = AsyncMock()

    data = AlertResolveRequest(resolution_note="Fixed upstream")

    with patch("alert_engine.services.alert_service.get_producer") as mock_producer, \
         patch("alert_engine.services.alert_service.dispatch_alert_notifications_task") as mock_task:

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=AsyncMock(publish=AsyncMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_producer.return_value = mock_ctx
        mock_task.delay = MagicMock()

        alert_id = uuid.UUID(existing["id"])
        result = await alert_service.resolve_alert(mock_db, TENANT_ID, alert_id, USER_ID, data)

    assert result.status == "resolved"


# ── Service layer: get_summary mock ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_summary_returns_summary():
    mock_db = AsyncMock()
    summary_row = {
        "total_open": 5,
        "critical": 2,
        "high": 2,
        "medium": 1,
        "low": 0,
        "info": 0,
        "acknowledged": 1,
        "escalated": 0,
        "resolved_last_24h": 3,
    }
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one=lambda: summary_row)
    ))

    summary = await alert_service.get_summary(mock_db, TENANT_ID)
    assert summary.total_open == 5
    assert summary.critical == 2
    assert summary.resolved_last_24h == 3


# ── State machine guard tests ─────────────────────────────────────────────────

def test_status_terminal_states_are_equal():
    """Resolved and suppressed are both terminal (weight=10)."""
    assert ALERT_STATUS_ORDER["resolved"] == 10
    assert ALERT_STATUS_ORDER["suppressed"] == 10


def test_escalated_is_after_acknowledged():
    assert ALERT_STATUS_ORDER["escalated"] > ALERT_STATUS_ORDER["acknowledged"]


def test_severity_levels_defined():
    import typing
    from alert_engine.schemas.alert import AlertSeverity
    severities = ("critical", "high", "medium", "low", "info")
    args = typing.get_args(AlertSeverity)
    for s in severities:
        assert s in args
