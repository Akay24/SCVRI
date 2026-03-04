"""Pytest configuration and shared fixtures for risk-intelligence tests."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SUPPLIER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
KRI_DEFINITION_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
MODEL_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


# ── DB Session Stub ──────────────────────────────────────────────────────────

def make_db_mock() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


# ── Request State Stub ───────────────────────────────────────────────────────

class FakeState:
    tenant_id: uuid.UUID = TENANT_ID
    user_id: uuid.UUID = USER_ID
    role: str = "risk_analyst"
    scopes: list[str] = []


# ── Kafka producer mock ──────────────────────────────────────────────────────

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


# ── ML predictor mock ────────────────────────────────────────────────────────

@pytest.fixture()
def mock_predict():
    """Return a fixed risk probability of 0.42 (maps to 'medium' level)."""
    import numpy as np  # noqa: PLC0415
    from risk_intelligence.ml.predictor import PredictionResult  # noqa: PLC0415

    result = PredictionResult(
        risk_score=42.0,
        risk_level="medium",
        model_id=MODEL_ID,
        model_version="1.0.0",
        feature_importances={},
        component_scores=[],
    )
    with patch("risk_intelligence.services.risk_scoring_service.predictor.predict", return_value=result) as m:
        yield m


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    from risk_intelligence.main import create_app  # noqa: PLC0415
    return create_app()


@pytest.fixture()
def client(app):
    from risk_intelligence.dependencies import require_write_access, require_ml_admin  # noqa: PLC0415

    state = FakeState()

    async def fake_write():
        return None

    async def fake_ml_admin():
        return None

    app.dependency_overrides[require_write_access] = fake_write
    app.dependency_overrides[require_ml_admin] = fake_ml_admin

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def async_client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
