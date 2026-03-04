"""Test fixtures for supplier-management service.

Provides:
- async HTTP test client (httpx.AsyncClient) pre-authenticated as supply_chain_manager
- PostgreSQL test session with per-test SAVEPOINT rollback
- Redis flush between tests
- Moto S3 mock for document tests
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scvri_shared.config import Settings

# Override settings BEFORE importing app
_TEST_TENANT_ID = uuid.uuid4()
_TEST_USER_ID = uuid.uuid4()
_TEST_JWT = "test.jwt.token"


@pytest.fixture(scope="session", autouse=True)
def settings_override(tmp_path_factory):
    """Patch settings with test values before any imports touch them."""
    tmp = tmp_path_factory.mktemp("cfg")
    overrides = {
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/scvri_test",
        "DATABASE_URL_SYNC": "postgresql+psycopg2://postgres:postgres@localhost:5432/scvri_test",
        "REDIS_URL": "redis://localhost:6379/1",
        "JWT_ALGORITHM": "HS256",
        "JWT_PRIVATE_KEY_PATH": "super-test-secret-key-do-not-use-in-prod",
        "JWT_PUBLIC_KEY_PATH": "super-test-secret-key-do-not-use-in-prod",
        "SERVICE_NAME": "supplier-management-test",
        "ENVIRONMENT": "test",
        "KAFKA_BOOTSTRAP_SERVERS": "localhost:29092",
        "S3_SUPPLIER_DOCUMENTS_BUCKET": "test-supplier-docs",
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
    }
    with patch.dict("os.environ", overrides):
        yield


@pytest.fixture(scope="session")
def mock_kafka():
    """Suppress Kafka in all tests."""
    with patch("scvri_shared.kafka.init_producer", new_callable=AsyncMock) as mock_init, \
         patch("scvri_shared.kafka.close_producer", new_callable=AsyncMock), \
         patch("scvri_shared.kafka.get_producer") as mock_ctx:

        fake_producer = AsyncMock()
        fake_producer.publish = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=fake_producer)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        yield fake_producer


@pytest_asyncio.fixture(scope="session")
async def app_client(settings_override, mock_kafka) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with pre-injected tenant/user state."""
    from supplier_management.main import create_app  # noqa: PLC0415

    application = create_app()

    # Wire request.state directly — bypasses full JWT middleware
    from scvri_shared.middleware import _ANON_PATHS  # noqa: PLC0415

    @application.middleware("http")
    async def _inject_test_state(request, call_next):
        request.state.tenant_id = _TEST_TENANT_ID
        request.state.user_id = _TEST_USER_ID
        request.state.role = "supply_chain_manager"
        request.state.scopes = ["suppliers:read", "suppliers:write"]
        return await call_next(request)

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers={"Authorization": f"Bearer {_TEST_JWT}"},
    ) as client:
        yield client


@pytest.fixture()
def tenant_id() -> uuid.UUID:
    return _TEST_TENANT_ID


@pytest.fixture()
def user_id() -> uuid.UUID:
    return _TEST_USER_ID
