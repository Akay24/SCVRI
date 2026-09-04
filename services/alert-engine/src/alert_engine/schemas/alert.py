"""Alert schemas (pydantic v2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import field_validator, model_validator

from scvri_shared.schemas import CamelBase

# ── Enums ─────────────────────────────────────────────────────────────────────

AlertSeverity = Literal["critical", "high", "medium", "low", "info"]

AlertStatus = Literal[
    "open",
    "acknowledged",
    "resolved",
    "suppressed",
    "escalated",
]

AlertSource = Literal[
    "risk_engine",       # risk.events topic
    "visibility",        # visibility.events topic
    "supplier",          # supplier.events topic
    "integration",       # integration.events topic
    "manual",            # created by user via API
    "scheduled_rule",    # CEP / scheduled rule match
    "system",            # system / internal alert
]

# Status ordering for escalation logic
ALERT_STATUS_ORDER = {
    "open": 0,
    "acknowledged": 1,
    "escalated": 2,
    "resolved": 10,
    "suppressed": 10,
}


# ── Alerts CRUD ───────────────────────────────────────────────────────────────

class AlertCreate(CamelBase):
    title: str
    description: str
    severity: AlertSeverity
    source: AlertSource
    source_event_type: str | None = None
    source_event_id: str | None = None      # originating event/correlation ID
    supplier_id: uuid.UUID | None = None
    rule_id: uuid.UUID | None = None
    payload: dict = {}

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title cannot be blank")
        return v.strip()


class AlertUpdate(CamelBase):
    status: AlertStatus | None = None
    resolution_notes: str | None = None
    assignee_id: uuid.UUID | None = None


class AlertResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    description: str
    severity: AlertSeverity
    status: AlertStatus
    source: AlertSource
    source_event_type: str | None
    source_event_id: str | None
    supplier_id: uuid.UUID | None
    rule_id: uuid.UUID | None
    payload: dict
    assignee_id: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    suppressed_until: datetime | None
    resolution_notes: str | None
    escalated_at: datetime | None
    notification_count: int
    created_at: datetime
    updated_at: datetime


class AlertAcknowledgeRequest(CamelBase):
    note: str | None = None
    notes: str | None = None
    assignee_id: uuid.UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_note(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "notes" in data and "note" not in data:
                data["note"] = data["notes"]
            elif "note" in data and "notes" not in data:
                data["notes"] = data["note"]
        return data


class AlertResolveRequest(CamelBase):
    resolution_note: str | None = None
    resolution_notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_resolution(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "resolution_note" in data and not data.get("resolution_notes"):
                data["resolution_notes"] = data["resolution_note"]
            elif "resolution_notes" in data and not data.get("resolution_note"):
                data["resolution_note"] = data["resolution_notes"]
        return data


class AlertSuppressRequest(CamelBase):
    until: datetime | None = None
    suppress_until: datetime | None = None
    reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_until(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "until" in data and "suppress_until" not in data:
                data["suppress_until"] = data["until"]
            elif "suppress_until" in data and "until" not in data:
                data["until"] = data["suppress_until"]
        return data

    @model_validator(mode="after")
    def _validate_future(self) -> "AlertSuppressRequest":
        target = self.until or self.suppress_until
        if target is None:
            raise ValueError("until or suppress_until is required")
        if target <= datetime.now(timezone.utc):
            raise ValueError("until must be in the future")
        self.until = target
        self.suppress_until = target
        return self


class AlertEscalateRequest(CamelBase):
    assignee_id: uuid.UUID | None = None
    escalate_to_user_id: uuid.UUID | None = None
    note: str | None = None
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_escalate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "assignee_id" in data and "escalate_to_user_id" not in data:
                data["escalate_to_user_id"] = data["assignee_id"]
            elif "escalate_to_user_id" in data and "assignee_id" not in data:
                data["assignee_id"] = data["escalate_to_user_id"]
            if "note" in data and not data.get("reason"):
                data["reason"] = data["note"]
            elif "reason" in data and not data.get("note"):
                data["note"] = data["reason"]
        return data



# ── Alert summary ─────────────────────────────────────────────────────────────

class AlertSummaryResponse(CamelBase):
    total_open: int
    critical: int
    high: int
    medium: int
    low: int
    info: int
    acknowledged: int
    escalated: int
    resolved_last_24h: int
