"""Pytest configuration and shared fixtures for the SCVRI shared library tests.

Fixtures provided:
  - event_loop        — module-scoped asyncio event loop
  - pg_engine         — sync SQLAlchemy engine pointing at test DB
  - async_engine      — async SQLAlchemy engine
  - db_session        — async session with per-test SAVEPOINT rollback
  - redis_client      — async Redis client
  - settings_override — overrides env vars for tests
  - sample_tenant     — creates a Tenant row and yields it
  - sample_user       — creates a User row and yields it
  - sample_supplier   — creates a Supplier row and yields it
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# --- point at test database ------------------------------------------------
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://scvri:scvri_dev_password@localhost:5432/scvri_test",
)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://:redis_dev_password@localhost:6379/1")


# ---------------------------------------------------------------------------
# Event loop — module scope so we can share across async fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Force test settings before any import of scvri_shared.config
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def settings_override() -> Generator[None, None, None]:
    overrides = {
        "DATABASE_URL": TEST_DB_URL.replace("+asyncpg", ""),
        "ASYNC_DATABASE_URL": TEST_DB_URL,
        "REDIS_URL": TEST_REDIS_URL,
        "JWT_ALGORITHM": "HS256",   # Use HMAC for tests (no RSA key needed)
        "JWT_PRIVATE_KEY_PEM": "test-secret-key",
        "JWT_PUBLIC_KEY_PEM": "test-secret-key",
        "SERVICE_NAME": "test-service",
        "ENVIRONMENT": "development",
        "S3_SUPPLIER_DOCS_BUCKET": "test-bucket",
        "KMS_PII_KEY_ID": "test-kms-key",
        "KAFKA_BOOTSTRAP_SERVERS": "localhost:29092",
    }
    with patch.dict(os.environ, overrides):
        yield


# ---------------------------------------------------------------------------
# Async engine + session
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def async_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Each test gets an async session wrapped in a SAVEPOINT for automatic rollback."""
    async with async_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()  # SAVEPOINT

        AsyncSessionFactory = sessionmaker(  # noqa: N806
            bind=conn, class_=AsyncSession, expire_on_commit=False
        )
        session = AsyncSessionFactory()

        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def redis_client():
    import redis.asyncio as aioredis  # noqa: PLC0415
    r = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    yield r
    await r.flushdb()
    await r.aclose()


# ---------------------------------------------------------------------------
# Domain object factories
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def sample_tenant(db_session: AsyncSession):
    from scvri_shared.models.tenant import Tenant  # noqa: PLC0415

    tenant = Tenant(
        id=uuid.uuid4(),
        name="Test Corp",
        slug=f"test-corp-{uuid.uuid4().hex[:8]}",
        plan="enterprise",
        max_suppliers=1000,
        max_users=100,
        data_region="us-east-1",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest_asyncio.fixture()
async def sample_user(db_session: AsyncSession, sample_tenant):
    from scvri_shared.models.auth import User  # noqa: PLC0415
    from scvri_shared.security import hash_password  # noqa: PLC0415

    user = User(
        id=uuid.uuid4(),
        tenant_id=sample_tenant.id,
        email=f"admin-{uuid.uuid4().hex[:8]}@testcorp.dev",
        first_name="Test",
        last_name="Admin",
        password_hash=hash_password("P@ssw0rd!Test123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture()
async def sample_supplier(db_session: AsyncSession, sample_tenant):
    from scvri_shared.models.supplier import Supplier  # noqa: PLC0415

    supplier = Supplier(
        id=uuid.uuid4(),
        tenant_id=sample_tenant.id,
        legal_name="Acme Testing Supply Co.",
        trading_name="Acme Testing",
        country_code="US",
        status="active",
        onboarding_status="active",
        tier="preferred",
        primary_category="Electronics",
    )
    db_session.add(supplier)
    await db_session.flush()
    return supplier


# ---------------------------------------------------------------------------
# Mock Kafka producer (used by tests that trigger Kafka publishes)
# ---------------------------------------------------------------------------
@pytest.fixture()
def mock_kafka_producer():
    mock = AsyncMock()
    mock.publish = AsyncMock(return_value=None)
    with patch("scvri_shared.kafka.init_producer", return_value=mock):
        yield mock
