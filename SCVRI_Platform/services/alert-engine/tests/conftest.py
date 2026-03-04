"""Shared test fixtures for alert-engine."""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alert_engine.main import create_app
from alert_engine.schemas.alert import AlertCreate, AlertSeverity, AlertSource, AlertStatus
from alert_engine.schemas.rule import AlertRuleCreate, RuleCondition
from alert_engine.schemas.notification import (
    EmailChannelConfig,
    NotificationChannelCreate,
    SlackChannelConfig,
    WebhookChannelConfig,
)

# ── Constants ─────────────────────────────────────────────────────────────────

TENANT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
ADMIN_CLAIMS = {
    "tenant_id": str(TENANT_ID),
    "user_id": str(USER_ID),
    "roles": ["it_administrator"],
    "sub": str(USER_ID),
}

# ── DB Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory async SQLite session for unit tests (structural tests only)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        yield session

    await engine.dispose()


# ── App + HTTP client ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client with JWT auth bypassed (admin claims injected)."""
    app = create_app()

    # Patch auth dependency to return synthetic claims
    from scvri_shared.auth import TokenClaims  # noqa: PLC0415

    async def _fake_claims() -> TokenClaims:
        return TokenClaims(**ADMIN_CLAIMS)

    from alert_engine.dependencies import require_write_access, require_admin  # noqa: PLC0415

    app.dependency_overrides[require_write_access] = _fake_claims
    app.dependency_overrides[require_admin] = _fake_claims

    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


# ── Data factories ────────────────────────────────────────────────────────────

def make_alert_create(
    *,
    severity: AlertSeverity = "high",
    source: AlertSource = "manual",
    supplier_id: uuid.UUID | None = None,
    rule_id: uuid.UUID | None = None,
) -> AlertCreate:
    return AlertCreate(
        title="Test Alert",
        description="This is a test alert description.",
        severity=severity,
        source=source,
        source_event_type="test.event",
        source_event_id=str(uuid.uuid4()),
        supplier_id=supplier_id,
        rule_id=rule_id,
        payload={"key": "value"},
    )


def make_rule_create(
    *,
    name: str = "Test Rule",
    trigger_type: str = "event",
    event_topics: list[str] | None = None,
    event_types: list[str] | None = None,
    conditions: list[RuleCondition] | None = None,
    cooldown_seconds: int = 3600,
) -> AlertRuleCreate:
    return AlertRuleCreate(
        name=name,
        trigger_type=trigger_type,
        event_topics=event_topics or ["risk.events"],
        event_types=event_types or ["risk.score.changed"],
        conditions=conditions or [
            RuleCondition(field="score", operator="lt", value=40, description="Score below 40")
        ],
        severity="high",
        alert_title_template="Risk Alert: {{ supplier_name }}",
        alert_description_template="Supplier {{ supplier_name }} score dropped to {{ score }}",
        cooldown_seconds=cooldown_seconds,
    )


def make_email_channel_create(recipients: list[str] | None = None) -> NotificationChannelCreate:
    return NotificationChannelCreate(
        name="Test Email Channel",
        channel_type="email",
        config=EmailChannelConfig(
            recipients=recipients or ["test@example.com"],
            subject_prefix="[TEST]",
        ),
        min_severity="medium",
        is_active=True,
    )


def make_slack_channel_create() -> NotificationChannelCreate:
    return NotificationChannelCreate(
        name="Test Slack Channel",
        channel_type="slack",
        config=SlackChannelConfig(
            webhook_url="https://hooks.slack.com/services/T000/B000/xxxx",
            channel="#alerts",
        ),
        min_severity="high",
        is_active=True,
    )


def make_webhook_channel_create() -> NotificationChannelCreate:
    return NotificationChannelCreate(
        name="Test Webhook Channel",
        channel_type="webhook",
        config=WebhookChannelConfig(
            url="https://example.com/webhook",
            method="POST",
            retry_attempts=2,
        ),
        min_severity="medium",
        is_active=True,
    )
