"""Tests for ERP connectors and rate limiter."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx

from tests.conftest import TENANT_ID

if TYPE_CHECKING:
    from integration.schemas.erp import ERPConnectionConfig


def _make_config(system: str = "sap") -> ERPConnectionConfig:
    from integration.schemas.erp import ERPConnectionConfig, ERPSystem

    return ERPConnectionConfig(
        system=ERPSystem(system),
        base_url="https://erp.example.com",
        client_id="client_id",
        client_secret="client_secret",
        tenant_id=TENANT_ID,
    )


# ── CircuitBreaker ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_closed_on_success():
    from integration.core.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test", failure_threshold=3)
    assert cb.state == CircuitBreaker.CLOSED

    async def succeed() -> str:
        return "ok"

    result = await cb.call(succeed)
    assert result == "ok"
    assert cb.state == CircuitBreaker.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    from integration.core.circuit_breaker import CircuitBreaker, CircuitOpenError

    cb = CircuitBreaker("test", failure_threshold=2)

    async def fail() -> None:
        raise ValueError("boom")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)

    assert cb.state == CircuitBreaker.OPEN

    with pytest.raises(CircuitOpenError):
        await cb.call(fail)


@pytest.mark.asyncio
async def test_circuit_breaker_recovers():
    from integration.core.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0, success_threshold=1)

    async def fail() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await cb.call(fail)

    assert cb.state == CircuitBreaker.OPEN

    # Manually set opened_at far in the past to simulate timeout elapsed
    cb._opened_at = 0  # epoch — long ago

    async def succeed() -> str:
        return "ok"

    result = await cb.call(succeed)
    assert result == "ok"
    assert cb.state == CircuitBreaker.CLOSED


# ── SlidingWindowRateLimiter ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit(mock_redis):
    from integration.core.rate_limiter import SlidingWindowRateLimiter

    mock_redis.register_script = MagicMock(return_value=AsyncMock(return_value=1))
    rl = SlidingWindowRateLimiter(mock_redis, limit=10, window=60, prefix="rl")
    allowed = await rl.is_allowed("tenant:sap")
    assert allowed is True


@pytest.mark.asyncio
async def test_rate_limiter_rejects_when_exceeded(mock_redis):
    from integration.core.rate_limiter import RateLimitExceeded, SlidingWindowRateLimiter

    mock_redis.register_script = MagicMock(return_value=AsyncMock(return_value=0))
    rl = SlidingWindowRateLimiter(mock_redis, limit=1, window=60, prefix="rl")
    with pytest.raises(RateLimitExceeded):
        await rl.check("tenant:sap")


# ── SAPConnector ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_sap_authenticate_success():
    from integration.connectors.sap import SAPConnector

    config = _make_config("sap")
    connector = SAPConnector(config)
    # Patch httpx transport
    respx.post("https://erp.example.com/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok123"})
    )
    connector._client = httpx.AsyncClient(base_url=config.base_url)
    await connector.authenticate()
    assert connector._access_token == "tok123"
    await connector._client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_sap_fetch_entities_success():
    from integration.connectors.sap import SAPConnector
    from integration.schemas.erp import ERPEntityType

    config = _make_config("sap")
    connector = SAPConnector(config)
    connector._access_token = "tok123"

    records = [{"BusinessPartner": "BP001", "LastChangeDateTime": "2026-01-01T00:00:00"}]
    respx.get("https://erp.example.com/API_BUSINESS_PARTNER/A_BusinessPartner").mock(
        return_value=httpx.Response(200, json={"value": records})
    )

    connector._client = httpx.AsyncClient(base_url=config.base_url)
    result = await connector.fetch_entities(ERPEntityType.SUPPLIER)
    assert len(result) == 1
    assert result[0]["BusinessPartner"] == "BP001"
    await connector._client.aclose()


@pytest.mark.asyncio
async def test_sap_normalise_supplier():
    from integration.connectors.sap import SAPConnector
    from integration.schemas.erp import ERPEntityType, ERPSystem

    config = _make_config("sap")
    connector = SAPConnector(config)
    raw = {
        "BusinessPartner": "BP001",
        "BusinessPartnerFullName": "Acme Corp",
        "LastChangeDateTime": "2026-01-15T10:30:00",
    }
    event = connector.normalise(ERPEntityType.SUPPLIER, raw)
    assert event.source_id == "BP001"
    assert event.source_system == ERPSystem.SAP
    assert event.tenant_id == TENANT_ID


# ── OracleConnector ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oracle_basic_auth():
    from integration.connectors.oracle import OracleConnector
    import base64

    config = _make_config("oracle")
    connector = OracleConnector(config)
    connector._client = MagicMock()  # not used for basic auth
    await connector.authenticate()
    expected = base64.b64encode(b"client_id:client_secret").decode()
    assert connector._access_token == f"Basic {expected}"


@pytest.mark.asyncio
@respx.mock
async def test_oracle_fetch_entities_success():
    from integration.connectors.oracle import OracleConnector
    from integration.schemas.erp import ERPEntityType
    import base64

    config = _make_config("oracle")
    connector = OracleConnector(config)
    creds = base64.b64encode(b"client_id:client_secret").decode()
    connector._access_token = f"Basic {creds}"

    records = [{"SupplierId": "1001", "SupplierName": "Oracle Corp", "LastUpdateDate": "2026-01-01T00:00:00"}]
    respx.get("https://erp.example.com/fscmRestApi/resources/11.13.18.05/suppliers").mock(
        return_value=httpx.Response(200, json={"items": records, "hasMore": False})
    )

    connector._client = httpx.AsyncClient(base_url=config.base_url)
    result = await connector.fetch_entities(ERPEntityType.SUPPLIER)
    assert len(result) == 1
    await connector._client.aclose()


@pytest.mark.asyncio
async def test_oracle_normalise_supplier():
    from integration.connectors.oracle import OracleConnector
    from integration.schemas.erp import ERPEntityType, ERPSystem

    config = _make_config("oracle")
    connector = OracleConnector(config)
    raw = {
        "SupplierId": "1001",
        "SupplierName": "Test Corp",
        "LastUpdateDate": "2026-02-15T08:00:00",
    }
    event = connector.normalise(ERPEntityType.SUPPLIER, raw)
    assert event.source_id == "1001"
    assert event.source_system == ERPSystem.ORACLE


# ── get_connector factory ─────────────────────────────────────────────────────

def test_get_connector_returns_sap():
    from integration.connectors import get_connector
    from integration.connectors.sap import SAPConnector

    config = _make_config("sap")
    connector = get_connector(config)
    assert isinstance(connector, SAPConnector)


def test_get_connector_returns_oracle():
    from integration.connectors import get_connector
    from integration.connectors.oracle import OracleConnector

    config = _make_config("oracle")
    connector = get_connector(config)
    assert isinstance(connector, OracleConnector)


def test_get_connector_unknown_raises():
    from integration.connectors import get_connector
    from integration.schemas.erp import ERPConnectionConfig, ERPSystem

    config = ERPConnectionConfig(
        system=ERPSystem.GENERIC,
        base_url="https://erp.example.com",
        client_id="id",
        client_secret="sec",
        tenant_id=TENANT_ID,
    )
    with pytest.raises(ValueError, match="No connector registered"):
        get_connector(config)
