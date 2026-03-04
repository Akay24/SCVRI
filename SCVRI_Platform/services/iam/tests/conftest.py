"""Shared fixtures for IAM tests."""
from __future__ import annotations

import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Generate a test RS256 keypair ──────────────────────────────────────────────
# Generated once per test session so tests never need a real key file.

def _generate_rsa_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


_PRIVATE_PEM, _PUBLIC_PEM = _generate_rsa_keypair()

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
TEST_EMAIL = "test@acme.scvri.io"
TEST_PASSWORD = "Password1"


@pytest.fixture(autouse=True)
def patch_rsa_keys(monkeypatch):
    """Inject test RSA keys into the security module before each test."""
    import iam.core.security as sec  # noqa: PLC0415
    sec._private_key = _PRIVATE_PEM
    sec._public_key = _PUBLIC_PEM
    yield
    sec._private_key = None
    sec._public_key = None


@pytest.fixture()
def mock_redis():
    redis = AsyncMock()
    redis.setex = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=0)
    redis.getdel = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture()
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def make_user_row(
    user_id: uuid.UUID = USER_ID,
    tenant_id: uuid.UUID = TENANT_ID,
    email: str = TEST_EMAIL,
    role: str = "viewer",
    status: str = "active",
    mfa_enabled: bool = False,
    totp_secret: str | None = None,
) -> dict:
    from datetime import datetime, timezone  # noqa: PLC0415
    from iam.core.security import hash_password  # noqa: PLC0415

    return {
        "id": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "full_name": "Test User",
        "password_hash": hash_password(TEST_PASSWORD),
        "role": role,
        "status": status,
        "mfa_enabled": mfa_enabled,
        "mfa_method": "totp" if mfa_enabled else "none",
        "totp_secret": totp_secret,
        "pending_totp_secret": None,
        "external_id": None,
        "last_login_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
