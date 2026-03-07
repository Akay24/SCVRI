"""Shared pytest fixtures for Integration service tests."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ENDPOINT_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
REGISTRATION_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
SIGNING_SECRET = "supersecretkey1234567890abcdef"


def make_signature(body: bytes, secret: str = SIGNING_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.zremrangebyscore = AsyncMock(return_value=0)
    redis.zcard = AsyncMock(return_value=0)
    redis.zadd = AsyncMock(return_value=1)
    redis.pexpire = AsyncMock(return_value=1)
    redis.register_script = MagicMock(return_value=AsyncMock(return_value=1))
    return redis


@pytest.fixture
def webhook_registration_row() -> dict:
    return {
        "id": REGISTRATION_ID,
        "tenant_id": TENANT_ID,
        "source": "sap",
        "signing_secret": SIGNING_SECRET,
        "description": "Test registration",
        "active": True,
        "created_at": datetime.now(tz=timezone.utc),
    }


@pytest.fixture
def outbound_endpoint_row() -> dict:
    return {
        "id": ENDPOINT_ID,
        "tenant_id": TENANT_ID,
        "name": "Test endpoint",
        "url": "https://external.example.com/hooks",
        "secret": SIGNING_SECRET,
        "event_types": json.dumps(["risk_score.updated", "alert.triggered"]),
        "active": True,
        "timeout_seconds": 10,
        "retry_max": 3,
        "created_at": datetime.now(tz=timezone.utc),
    }
