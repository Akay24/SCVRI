"""Tests for webhook ingestion service and HMAC signature validation."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import (
    REGISTRATION_ID,
    SIGNING_SECRET,
    TENANT_ID,
    make_signature,
    webhook_registration_row,
)


# ── verify_webhook_signature ───────────────────────────────────────────────────

class TestVerifyWebhookSignature:
    def test_valid_signature(self):
        from integration.schemas.webhook import verify_webhook_signature

        body = b'{"event_type": "supplier.updated"}'
        sig = make_signature(body)
        assert verify_webhook_signature(body, sig, SIGNING_SECRET) is True

    def test_tampered_body(self):
        from integration.schemas.webhook import verify_webhook_signature

        body = b'{"event_type": "supplier.updated"}'
        sig = make_signature(body)
        tampered = b'{"event_type": "supplier.created"}'
        assert verify_webhook_signature(tampered, sig, SIGNING_SECRET) is False

    def test_wrong_secret(self):
        from integration.schemas.webhook import verify_webhook_signature

        body = b'{"event": "test"}'
        sig = make_signature(body, secret="right_secret")
        assert verify_webhook_signature(body, sig, "wrong_secret") is False

    def test_missing_sha256_prefix(self):
        from integration.schemas.webhook import verify_webhook_signature

        body = b'{"event": "test"}'
        raw_hex = hmac.new(SIGNING_SECRET.encode(), body, hashlib.sha256).hexdigest()
        # Pass without 'sha256=' prefix
        assert verify_webhook_signature(body, raw_hex, SIGNING_SECRET) is False

    def test_empty_body(self):
        from integration.schemas.webhook import verify_webhook_signature

        body = b""
        sig = make_signature(body)
        assert verify_webhook_signature(body, sig, SIGNING_SECRET) is True


# ── _infer_event_type ──────────────────────────────────────────────────────────

class TestInferEventType:
    def test_known_types(self):
        from integration.services.webhook_service import _infer_event_type
        from integration.schemas.webhook import WebhookEventType

        assert _infer_event_type("supplier.updated") == WebhookEventType.SUPPLIER_UPDATED
        assert _infer_event_type("purchase_order.created") == WebhookEventType.PURCHASE_ORDER_CREATED
        assert _infer_event_type("invoice.received") == WebhookEventType.INVOICE_RECEIVED

    def test_unknown_type(self):
        from integration.services.webhook_service import _infer_event_type
        from integration.schemas.webhook import WebhookEventType

        assert _infer_event_type("some.unknown.event") == WebhookEventType.UNKNOWN

    def test_case_insensitive(self):
        from integration.services.webhook_service import _infer_event_type
        from integration.schemas.webhook import WebhookEventType

        assert _infer_event_type("SUPPLIER.UPDATED") == WebhookEventType.SUPPLIER_UPDATED


# ── ingest_webhook ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_webhook_success(mock_db, mock_redis, webhook_registration_row):
    from integration.services.webhook_service import ingest_webhook
    from integration.core.rate_limiter import SlidingWindowRateLimiter

    body = json.dumps({
        "event_type": "supplier.updated",
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(tz=timezone.utc).isoformat(),
        "data": {"supplier_id": "SUP-001", "name": "Acme Corp"},
    }).encode()
    sig = make_signature(body)

    # Simulate DB returning registration
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(
            one_or_none=lambda: webhook_registration_row,
            one=lambda: {
                "id": uuid.uuid4(), "registration_id": REGISTRATION_ID,
                "event_id": "evt1", "event_type": "supplier.updated",
                "received_at": datetime.now(tz=timezone.utc),
                "signature_valid": True, "processed": True,
                "kafka_offset": 42, "error": None,
            },
        )
    ))

    rate_limiter = SlidingWindowRateLimiter(mock_redis, limit=500, window=60, prefix="rl:webhook")

    with patch(
        "integration.services.webhook_service.publish_webhook_event",
        return_value=42,
    ):
        log = await ingest_webhook(
            mock_db,
            rate_limiter,
            REGISTRATION_ID,
            body=body,
            signature_header=sig,
        )

    assert log.signature_valid is True
    assert log.processed is True


@pytest.mark.asyncio
async def test_ingest_webhook_invalid_signature(mock_db, mock_redis, webhook_registration_row):
    from integration.services.webhook_service import (
        WebhookSignatureError,
        ingest_webhook,
    )
    from integration.core.rate_limiter import SlidingWindowRateLimiter

    body = b'{"event_type": "supplier.updated", "data": {}}'
    bad_sig = "sha256=deadbeefdeadbeef"

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: webhook_registration_row)
    ))

    rate_limiter = SlidingWindowRateLimiter(mock_redis, limit=500, window=60, prefix="rl:webhook")

    with pytest.raises(WebhookSignatureError):
        await ingest_webhook(
            mock_db,
            rate_limiter,
            REGISTRATION_ID,
            body=body,
            signature_header=bad_sig,
        )


@pytest.mark.asyncio
async def test_ingest_webhook_rate_limited(mock_db, mock_redis, webhook_registration_row):
    from integration.services.webhook_service import ingest_webhook
    from integration.core.rate_limiter import RateLimitExceeded, SlidingWindowRateLimiter

    body = b'{"event_type": "supplier.updated"}'
    sig = make_signature(body)

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: webhook_registration_row)
    ))

    # Script returns 0 = rate limit exceeded
    mock_redis.register_script = MagicMock(return_value=AsyncMock(return_value=0))
    rate_limiter = SlidingWindowRateLimiter(mock_redis, limit=1, window=60, prefix="rl:webhook")

    with pytest.raises(RateLimitExceeded):
        await ingest_webhook(
            mock_db,
            rate_limiter,
            REGISTRATION_ID,
            body=body,
            signature_header=sig,
        )


@pytest.mark.asyncio
async def test_ingest_webhook_missing_registration(mock_db, mock_redis):
    from integration.services.webhook_service import WebhookNotFoundError, ingest_webhook
    from integration.core.rate_limiter import SlidingWindowRateLimiter

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: None)
    ))
    rate_limiter = SlidingWindowRateLimiter(mock_redis, limit=500, window=60)

    body = b"{}"
    with pytest.raises(WebhookNotFoundError):
        await ingest_webhook(mock_db, rate_limiter, uuid.uuid4(), body=body, signature_header=None)


# ── CRUD ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_webhook_registration(mock_db, webhook_registration_row):
    from integration.services.webhook_service import create_webhook_registration
    from integration.schemas.webhook import WebhookRegistration, WebhookSource

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one=lambda: webhook_registration_row)
    ))

    reg = WebhookRegistration(
        tenant_id=TENANT_ID,
        source=WebhookSource.SAP,
        signing_secret=SIGNING_SECRET,
        description="Test",
    )
    result = await create_webhook_registration(mock_db, reg)
    assert result.tenant_id == TENANT_ID
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_registrations(mock_db, webhook_registration_row):
    from integration.services.webhook_service import list_registrations

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(all=lambda: [webhook_registration_row, webhook_registration_row])
    ))

    results = await list_registrations(mock_db, TENANT_ID)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_delete_registration_success(mock_db):
    from integration.services.webhook_service import delete_registration

    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    deleted = await delete_registration(mock_db, REGISTRATION_ID, TENANT_ID)
    assert deleted is True


@pytest.mark.asyncio
async def test_delete_registration_not_found(mock_db):
    from integration.services.webhook_service import delete_registration

    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    deleted = await delete_registration(mock_db, uuid.uuid4(), TENANT_ID)
    assert deleted is False
