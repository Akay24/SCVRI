"""Pytest configuration and shared fixtures for visibility tests."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SUPPLIER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
PO_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
SHIPMENT_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


class FakeState:
    tenant_id: uuid.UUID = TENANT_ID
    user_id: uuid.UUID = USER_ID
    role: str = "supply_chain_manager"
    scopes: list[str] = []


def make_db_mock() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture()
def mock_producer():
    with patch("scvri_shared.kafka.get_producer") as mock_ctx:
        producer = AsyncMock()
        producer.send = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=producer)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = cm
        yield producer


@pytest.fixture(scope="session")
def app():
    from visibility.main import create_app  # noqa: PLC0415
    return create_app()


@pytest.fixture()
def client(app):
    from visibility.dependencies import require_write_access  # noqa: PLC0415

    async def fake_write():
        return None

    app.dependency_overrides[require_write_access] = fake_write

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
