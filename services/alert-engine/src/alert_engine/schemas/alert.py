"""Alert schemas (pydantic v2)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import field_validator

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
    "scorecard",         # scorecard.computed topic
    "manual",            # created via API
    "system",            # internal health checks
]

# Status ordering for escalation logic
ALERT_STATUS_ORDER = {
    "open": 0,
    "acknowledged": 1,
    "escalated": 2,
    "resolved": 10,
    "suppressed": 10,
}


# ── Alert schemas ──────────────────────────────────────────────────────────────

class AlertCreate(CamelBase):
    title: str
    description: str
    severity: AlertSeverity
    source: AlertSource
    source_event_type: str | None = None    # e.g. "risk.score.updated"
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
    notes: str | None = None
    assignee_id: uuid.UUID | None = None


class AlertResolveRequest(CamelBase):
    resolution_notes: str


class AlertSuppressRequest(CamelBase):
    suppress_until: datetime
    reason: str | None = None


class AlertEscalateRequest(CamelBase):
    escalate_to_user_id: uuid.UUID
    reason: str


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
