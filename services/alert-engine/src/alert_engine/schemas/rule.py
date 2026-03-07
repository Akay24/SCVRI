"""Alert rule schemas (pydantic v2).

Rules define when an alert should be auto-created in response to a Kafka event
or a periodic threshold evaluation.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Any

from pydantic import field_validator, model_validator

from scvri_shared.schemas import CamelBase

# ── Enums ─────────────────────────────────────────────────────────────────────

RuleTriggerType = Literal[
    "event",         # fires when a matching Kafka event arrives
    "threshold",     # fires when a metric crosses a threshold value
    "absence",       # fires when no data arrives within a time window
]

RuleConditionOperator = Literal["gt", "gte", "lt", "lte", "eq", "neq", "in", "contains"]

RuleStatus = Literal["active", "inactive", "draft"]


# ── Rule condition ────────────────────────────────────────────────────────────

class RuleCondition(CamelBase):
    """A single condition evaluated against event payload or metric value."""
    field: str                           # dot-path into payload, e.g. "risk_score"
    operator: RuleConditionOperator
    value: Any                           # threshold value or match value
    description: str | None = None

    @field_validator("field")
    @classmethod
    def field_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("condition field cannot be blank")
        return v.strip()


# ── Rule schema ────────────────────────────────────────────────────────────────

class AlertRuleCreate(CamelBase):
    name: str
    description: str | None = None
    trigger_type: RuleTriggerType
    # Event rules
    event_topics: list[str] = []          # e.g. ["risk.events", "visibility.events"]
    event_types: list[str] = []           # e.g. ["risk.score.updated"]
    # Conditions (all must match — AND logic)
    conditions: list[RuleCondition] = []
    severity: str = "medium"
    alert_title_template: str             # Jinja2 template, vars from event payload
    alert_description_template: str
    # Cooldown — prevents re-firing within N seconds
    cooldown_seconds: int = 3600
    # Suppression — do not fire during scheduled maintenance windows
    suppress_outside_hours: bool = False
    suppress_start_hour: int | None = None  # 0-23 UTC
    suppress_end_hour: int | None = None    # 0-23 UTC
    # Escalation — auto-escalate if not acknowledged within N minutes
    auto_escalate_minutes: int | None = None
    # Scope — None means all suppliers
    supplier_ids: list[uuid.UUID] = []
    is_global: bool = False               # applies to all tenants (platform admin only)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()

    @model_validator(mode="after")
    def event_rule_needs_topics(self) -> "AlertRuleCreate":
        if self.trigger_type == "event" and not self.event_topics:
            raise ValueError("event rules must specify at least one event_topic")
        return self

    @field_validator("cooldown_seconds")
    @classmethod
    def cooldown_min(cls, v: int) -> int:
        if v < 0:
            raise ValueError("cooldown_seconds cannot be negative")
        return v


class AlertRuleUpdate(CamelBase):
    name: str | None = None
    description: str | None = None
    conditions: list[RuleCondition] | None = None
    severity: str | None = None
    cooldown_seconds: int | None = None
    auto_escalate_minutes: int | None = None
    status: RuleStatus | None = None


class AlertRuleResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    trigger_type: RuleTriggerType
    event_topics: list[str]
    event_types: list[str]
    conditions: list[RuleCondition]
    severity: str
    alert_title_template: str
    alert_description_template: str
    cooldown_seconds: int
    suppress_outside_hours: bool
    suppress_start_hour: int | None
    suppress_end_hour: int | None
    auto_escalate_minutes: int | None
    supplier_ids: list[uuid.UUID]
    is_global: bool
    status: RuleStatus
    fire_count: int
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime
