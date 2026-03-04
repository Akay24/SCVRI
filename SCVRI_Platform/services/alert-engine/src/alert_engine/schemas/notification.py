"""Notification channel schemas (pydantic v2)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Any

from pydantic import field_validator, AnyHttpUrl

from scvri_shared.schemas import CamelBase

# ── Enums ─────────────────────────────────────────────────────────────────────

ChannelType = Literal["email", "slack", "webhook", "in_app", "sms"]

NotificationStatus = Literal["pending", "sent", "failed", "skipped"]

DeliveryCause = Literal[
    "alert_created",
    "alert_escalated",
    "alert_resolved",
    "digest",          # periodic summary digest
]


# ── Notification channel configuration ────────────────────────────────────────

class EmailChannelConfig(CamelBase):
    recipients: list[str]             # email addresses
    cc: list[str] = []
    subject_prefix: str = "[SCVRI Alert]"

    @field_validator("recipients")
    @classmethod
    def at_least_one_recipient(cls, v: list) -> list:
        if not v:
            raise ValueError("At least one recipient is required")
        return v


class SlackChannelConfig(CamelBase):
    webhook_url: str                  # Slack incoming webhook URL
    channel: str | None = None        # override default channel
    mention_user_ids: list[str] = []  # Slack user IDs to mention on critical


class WebhookChannelConfig(CamelBase):
    url: str
    method: Literal["POST", "PUT"] = "POST"
    headers: dict[str, str] = {}
    secret_header: str | None = None  # header name containing HMAC signature
    timeout_seconds: int = 10
    retry_attempts: int = 3


class InAppChannelConfig(CamelBase):
    user_ids: list[uuid.UUID] = []    # empty = all users in tenant
    link_url: str | None = None       # deep link in front-end


# ── Channel CRUD schemas ───────────────────────────────────────────────────────

class NotificationChannelCreate(CamelBase):
    name: str
    channel_type: ChannelType
    config: EmailChannelConfig | SlackChannelConfig | WebhookChannelConfig | InAppChannelConfig
    # Filter by severity — only send notifications at or above this level
    min_severity: Literal["critical", "high", "medium", "low", "info"] = "medium"
    # Only trigger for specific alert sources
    sources: list[str] = []           # empty = all sources
    is_active: bool = True
    # Optional: associate with specific rule IDs
    rule_ids: list[uuid.UUID] = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()


class NotificationChannelUpdate(CamelBase):
    name: str | None = None
    config: Any | None = None
    min_severity: str | None = None
    is_active: bool | None = None


class NotificationChannelResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    channel_type: ChannelType
    config: dict                       # serialised channel config
    min_severity: str
    sources: list[str]
    is_active: bool
    rule_ids: list[uuid.UUID]
    sent_count: int
    failed_count: int
    last_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── Notification log (per delivery attempt) ───────────────────────────────────

class NotificationLogResponse(CamelBase):
    id: uuid.UUID
    alert_id: uuid.UUID
    channel_id: uuid.UUID
    channel_type: ChannelType
    status: NotificationStatus
    cause: DeliveryCause
    recipient_summary: str            # e.g. "3 recipients", "#alerts channel"
    error_message: str | None
    attempt_count: int
    sent_at: datetime | None
    created_at: datetime


# ── Digest ────────────────────────────────────────────────────────────────────

class DigestConfig(CamelBase):
    """Configuration for periodic alert digest emails."""
    channel_id: uuid.UUID
    cron_expression: str = "0 8 * * *"  # daily at 08:00 UTC
    lookback_hours: int = 24
    include_resolved: bool = False
    min_severity: str = "medium"
