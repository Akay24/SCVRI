"""Tests for rule service — conditions, operators, template rendering."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alert_engine.schemas.rule import AlertRuleCreate, RuleCondition
from alert_engine.services.rule_service import (
    _apply_operator,
    _check_conditions,
    _get_nested,
    _render_template,
    _topic_to_source,
)
from tests.conftest import TENANT_ID, USER_ID, make_rule_create


# ── _get_nested ───────────────────────────────────────────────────────────────

def test_get_nested_simple_key():
    assert _get_nested({"score": 42}, "score") == 42


def test_get_nested_dot_path():
    data = {"supplier": {"risk": {"score": 35}}}
    assert _get_nested(data, "supplier.risk.score") == 35


def test_get_nested_missing_key():
    assert _get_nested({"a": 1}, "b") is None


def test_get_nested_partial_path():
    data = {"a": {"b": 5}}
    assert _get_nested(data, "a.b.c") is None


# ── _apply_operator ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("op,a,b,expected", [
    ("gt", 50, 40, True),
    ("gt", 40, 50, False),
    ("gte", 40, 40, True),
    ("gte", 39, 40, False),
    ("lt", 30, 40, True),
    ("lt", 50, 40, False),
    ("lte", 40, 40, True),
    ("lte", 41, 40, False),
    ("eq", "high", "high", True),
    ("eq", "high", "medium", False),
    ("neq", "high", "medium", True),
    ("neq", "high", "high", False),
    ("in", "active", ["active", "inactive"], True),
    ("in", "deleted", ["active", "inactive"], False),
    ("contains", "critical alert", "critical", True),
    ("contains", "normal alert", "critical", False),
])
def test_apply_operator(op, a, b, expected):
    assert _apply_operator(a, op, b) == expected


def test_apply_operator_unknown_returns_false():
    assert _apply_operator(10, "unknown_op", 10) is False


# ── _check_conditions ──────────────────────────────────────────────────────────

def test_check_conditions_all_pass():
    conditions = [
        RuleCondition(field="score", operator="lt", value=50),
        RuleCondition(field="status", operator="eq", value="active"),
    ]
    payload = {"score": 30, "status": "active"}
    assert _check_conditions(conditions, payload) is True


def test_check_conditions_one_fails():
    conditions = [
        RuleCondition(field="score", operator="lt", value=50),
        RuleCondition(field="status", operator="eq", value="active"),
    ]
    payload = {"score": 30, "status": "inactive"}
    assert _check_conditions(conditions, payload) is False


def test_check_conditions_empty_is_true():
    """No conditions = always match."""
    assert _check_conditions([], {"score": 99}) is True


def test_check_conditions_nested_field():
    conditions = [RuleCondition(field="supplier.score", operator="lt", value=40)]
    payload = {"supplier": {"score": 25}}
    assert _check_conditions(conditions, payload) is True


def test_check_conditions_missing_field_is_false():
    conditions = [RuleCondition(field="nonexistent", operator="eq", value="x")]
    assert _check_conditions(conditions, {}) is False


# ── _render_template ──────────────────────────────────────────────────────────

def test_render_template_substitution():
    tmpl = "Alert for {{ supplier_name }} — score: {{ score }}"
    result = _render_template(tmpl, {"supplier_name": "Acme Corp", "score": 35})
    assert "Acme Corp" in result
    assert "35" in result


def test_render_template_fallback_on_error():
    """Malformed template returns the raw template string."""
    tmpl = "{% if %}"  # invalid Jinja2
    result = _render_template(tmpl, {})
    assert result == tmpl


def test_render_template_missing_variable_renders_empty():
    tmpl = "Score: {{ score }}"
    result = _render_template(tmpl, {})
    assert "Score:" in result


# ── _topic_to_source ──────────────────────────────────────────────────────────

def test_topic_to_source_risk():
    assert _topic_to_source("risk.events") == "risk_engine"


def test_topic_to_source_visibility():
    assert _topic_to_source("visibility.events") == "visibility"


def test_topic_to_source_scorecard():
    assert _topic_to_source("scorecard.computed") == "scorecard"


def test_topic_to_source_unknown():
    assert _topic_to_source("unknown.topic") == "system"


# ── AlertRuleCreate schema validation ──────────────────────────────────────────

def test_rule_create_event_requires_topic():
    with pytest.raises(Exception):
        AlertRuleCreate(
            name="No Topics",
            trigger_type="event",
            event_topics=[],  # must have at least one
            conditions=[],
            severity="high",
            title_template="Title",
            description_template="Desc",
        )


def test_rule_create_cooldown_must_be_non_negative():
    with pytest.raises(Exception):
        make_rule_create(cooldown_seconds=-1)


def test_rule_create_valid_threshold():
    rule = AlertRuleCreate(
        name="Threshold Rule",
        trigger_type="threshold",
        event_topics=[],
        conditions=[RuleCondition(field="score", operator="lt", value=40)],
        severity="critical",
        alert_title_template="Score dropped",
        alert_description_template="Score is {{ score }}",
        cooldown_seconds=0,
    )
    assert rule.trigger_type == "threshold"


# ── evaluate_event_rules integration-style mock test ─────────────────────────

@pytest.mark.asyncio
async def test_evaluate_event_rules_fires_matching_rule():
    """Matching rule fires and create_alert is called."""
    mock_db = AsyncMock()

    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    old_fired = now - timedelta(hours=5)

    rule_row = {
        "id": str(rule_id),
        "tenant_id": str(TENANT_ID),
        "name": "Low Score Rule",
        "trigger_type": "event",
        "event_topics": '["risk.events"]',
        "event_types": '["risk.score.changed"]',
        "conditions": '[{"field":"score","operator":"lt","value":50,"description":""}]',
        "severity": "high",
        "alert_title_template": "Low score: {{ score }}",
        "alert_description_template": "Score is {{ score }}",
        "cooldown_seconds": 3600,
        "suppress_outside_hours": False,
        "suppress_start_hour": 9,
        "suppress_end_hour": 17,
        "auto_escalate_minutes": None,
        "supplier_ids": "[]",
        "is_global": True,
        "status": "active",
        "fire_count": 0,
        "last_fired_at": old_fired,
        "created_at": now,
        "updated_at": now,
    }

    # Sequence: list_rules query → update fire_count
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(mappings=lambda: MagicMock(all=lambda: [rule_row])),  # fetch rules
        AsyncMock(),  # update fire_count
    ])
    mock_db.commit = AsyncMock()

    with patch(
        "alert_engine.services.rule_service.alert_service.create_alert",
        new_callable=AsyncMock,
    ) as mock_create:
        from alert_engine.schemas.alert import AlertResponse  # noqa: PLC0415
        mock_create.return_value = MagicMock(id=uuid.uuid4())

        from alert_engine.services.rule_service import evaluate_event_rules  # noqa: PLC0415
        fired = await evaluate_event_rules(
            mock_db,
            tenant_id=TENANT_ID,
            event_topic="risk.events",
            event_type="risk.score.changed",
            event_payload={"score": 30, "supplier_name": "Acme"},
        )

    mock_create.assert_awaited_once()
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_evaluate_event_rules_respects_cooldown():
    """Rule within cooldown window should not fire."""
    mock_db = AsyncMock()

    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    recent_fired = now - timedelta(minutes=10)  # fired 10 min ago; cooldown = 3600s

    rule_row = {
        "id": str(rule_id),
        "tenant_id": str(TENANT_ID),
        "name": "Cooldown Rule",
        "trigger_type": "event",
        "event_topics": '["risk.events"]',
        "event_types": '["risk.score.changed"]',
        "conditions": '[]',
        "severity": "medium",
        "alert_title_template": "Title",
        "alert_description_template": "Desc",
        "cooldown_seconds": 3600,
        "suppress_outside_hours": False,
        "suppress_start_hour": 9,
        "suppress_end_hour": 17,
        "auto_escalate_minutes": None,
        "supplier_ids": "[]",
        "is_global": True,
        "status": "active",
        "fire_count": 1,
        "last_fired_at": recent_fired,
        "created_at": now,
        "updated_at": now,
    }

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(all=lambda: [rule_row])
    ))
    mock_db.commit = AsyncMock()

    with patch(
        "alert_engine.services.rule_service.alert_service.create_alert",
        new_callable=AsyncMock,
    ) as mock_create:
        from alert_engine.services.rule_service import evaluate_event_rules  # noqa: PLC0415
        fired = await evaluate_event_rules(
            mock_db,
            tenant_id=TENANT_ID,
            event_topic="risk.events",
            event_type="risk.score.changed",
            event_payload={"score": 30},
        )

    mock_create.assert_not_awaited()
    assert len(fired) == 0
