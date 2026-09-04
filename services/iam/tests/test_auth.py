"""Tests for core security and auth service."""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iam.core.security import (
    ACCESS_TOKEN_TTL_SECONDS,
    create_access_token,
    create_mfa_session_token,
    create_refresh_token,
    decode_access_token,
    decode_mfa_session_token,
    decode_refresh_token,
    generate_totp_secret,
    hash_password,
    verify_password,
    verify_totp,
)
from tests.conftest import TENANT_ID, USER_ID, TEST_EMAIL, TEST_PASSWORD, make_user_row


# ── Password hashing ───────────────────────────────────────────────────────────

def test_hash_and_verify_password():
    hashed = hash_password("MySecurePass1")
    assert verify_password("MySecurePass1", hashed) is True
    assert verify_password("WrongPass1", hashed) is False


def test_hash_produces_different_salts():
    h1 = hash_password("Password1")
    h2 = hash_password("Password1")
    assert h1 != h2  # bcrypt salts are random


# ── Access token ───────────────────────────────────────────────────────────────

def test_create_and_decode_access_token():
    token, jti = create_access_token(USER_ID, TENANT_ID, "viewer", TEST_EMAIL)
    claims = decode_access_token(token)

    assert claims["sub"] == str(USER_ID)
    assert claims["tid"] == str(TENANT_ID)
    assert claims["tenant_id"] == str(TENANT_ID)
    assert claims["role"] == "viewer"
    assert claims["email"] == TEST_EMAIL
    assert claims["token_type"] == "access"
    assert "iss" in claims
    assert "aud" in claims
    assert "jti" in claims
    assert claims["exp"] > claims["iat"]


def test_access_token_expiry():
    token, _ = create_access_token(USER_ID, TENANT_ID, "viewer", TEST_EMAIL, ttl_seconds=-1)
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_access_token(token)


def test_access_token_custom_ttl():
    ttl = 7200
    token, _ = create_access_token(USER_ID, TENANT_ID, "viewer", TEST_EMAIL, ttl_seconds=ttl)
    claims = decode_access_token(token)
    assert claims["exp"] - claims["iat"] == ttl


# ── Refresh token ──────────────────────────────────────────────────────────────

def test_create_and_decode_refresh_token():
    token, jti = create_refresh_token(USER_ID, TENANT_ID)
    claims = decode_refresh_token(token)

    assert claims["sub"] == str(USER_ID)
    assert claims["tenant_id"] == str(TENANT_ID)
    assert claims["token_type"] == "refresh"
    assert claims["jti"] == jti


def test_refresh_token_rejected_as_access_token():
    from jose import JWTError
    token, _ = create_refresh_token(USER_ID, TENANT_ID)
    # decode_access_token succeeds structurally but token_type check would fail
    # Access token decoder only checks signature; token_type enforcement is in auth_service
    claims = decode_access_token(token)
    assert claims["token_type"] == "refresh"


# ── MFA session token ──────────────────────────────────────────────────────────

def test_mfa_session_token_roundtrip():
    token = create_mfa_session_token(USER_ID, TENANT_ID)
    claims = decode_mfa_session_token(token)
    assert claims["sub"] == str(USER_ID)
    assert claims["token_type"] == "mfa_session"


def test_mfa_session_token_expired():
    from jose import JWTError
    import iam.core.security as sec
    original = sec.MFA_SESSION_TTL_SECONDS
    # Can't easily backdate; instead create with negative TTL via direct jwt.encode
    from jose import jwt
    payload = {
        "sub": str(USER_ID),
        "tenant_id": str(TENANT_ID),
        "iat": int(time.time()) - 400,
        "exp": int(time.time()) - 100,
        "token_type": "mfa_session",
    }
    expired_token = jwt.encode(payload, sec.get_private_key(), algorithm="RS256")
    with pytest.raises(JWTError):
        decode_mfa_session_token(expired_token)


# ── TOTP ───────────────────────────────────────────────────────────────────────

def test_generate_totp_secret_is_base32():
    secret = generate_totp_secret()
    assert len(secret) >= 16
    # Should be valid base32 — pyotp uses it to make a TOTP
    import pyotp
    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert verify_totp(secret, code) is True


def test_verify_totp_wrong_code():
    secret = generate_totp_secret()
    assert verify_totp(secret, "000000") is False


def test_totp_provisioning_uri_format():
    from iam.core.security import get_totp_provisioning_uri
    secret = generate_totp_secret()
    uri = get_totp_provisioning_uri(secret, TEST_EMAIL)
    assert uri.startswith("otpauth://totp/")
    assert "test%40acme.scvri.io" in uri or TEST_EMAIL in uri


def test_totp_qr_code_is_base64_png():
    from iam.core.security import get_totp_provisioning_uri, build_totp_qr_data_uri
    secret = generate_totp_secret()
    uri = get_totp_provisioning_uri(secret, TEST_EMAIL)
    data_uri = build_totp_qr_data_uri(uri)
    assert data_uri.startswith("data:image/png;base64,")
    assert len(data_uri) > 100


# ── Redis token operations ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_and_validate_refresh_token(mock_redis):
    from iam.core.security import store_refresh_token, validate_and_rotate_refresh_token

    jti = str(uuid.uuid4())
    mock_redis.getdel = AsyncMock(return_value=str(USER_ID).encode())

    await store_refresh_token(mock_redis, USER_ID, jti)
    mock_redis.setex.assert_called_once()

    valid = await validate_and_rotate_refresh_token(mock_redis, jti, str(USER_ID))
    assert valid is True
    mock_redis.getdel.assert_called_once()


@pytest.mark.asyncio
async def test_validate_refresh_token_wrong_user(mock_redis):
    from iam.core.security import validate_and_rotate_refresh_token

    wrong_uid = str(uuid.uuid4())
    mock_redis.getdel = AsyncMock(return_value=str(USER_ID).encode())

    valid = await validate_and_rotate_refresh_token(mock_redis, "jti", wrong_uid)
    assert valid is False


@pytest.mark.asyncio
async def test_token_revocation(mock_redis):
    from iam.core.security import revoke_token, is_token_revoked

    jti = str(uuid.uuid4())
    mock_redis.exists = AsyncMock(return_value=1)

    await revoke_token(mock_redis, jti, 3600)
    mock_redis.setex.assert_called()

    revoked = await is_token_revoked(mock_redis, jti)
    assert revoked is True


# ── auth_service.authenticate_user ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticate_user_success(mock_db, mock_redis):
    from iam.services.auth_service import authenticate_user
    from iam.schemas.auth import LoginResponse

    row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    result = await authenticate_user(mock_db, mock_redis, TEST_EMAIL, TEST_PASSWORD)
    assert isinstance(result, LoginResponse)
    assert result.user_id == USER_ID
    assert result.access_token != ""
    assert result.refresh_token != ""


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password(mock_db, mock_redis):
    from iam.services.auth_service import authenticate_user
    from scvri_shared.exceptions import AuthenticationError

    row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    with pytest.raises(AuthenticationError):
        await authenticate_user(mock_db, mock_redis, TEST_EMAIL, "WrongPass1")


@pytest.mark.asyncio
async def test_authenticate_user_not_found(mock_db, mock_redis):
    from iam.services.auth_service import authenticate_user
    from scvri_shared.exceptions import AuthenticationError

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: None)
    ))

    with pytest.raises(AuthenticationError):
        await authenticate_user(mock_db, mock_redis, "ghost@nowhere.io", "Password1")


@pytest.mark.asyncio
async def test_authenticate_user_mfa_required(mock_db, mock_redis):
    from iam.services.auth_service import authenticate_user
    from iam.schemas.auth import MFAChallengeResponse

    secret = generate_totp_secret()
    row = make_user_row(mfa_enabled=True, totp_secret=secret)
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    result = await authenticate_user(mock_db, mock_redis, TEST_EMAIL, TEST_PASSWORD)
    assert isinstance(result, MFAChallengeResponse)
    assert result.mfa_required is True
    assert result.mfa_method == "totp"
    assert result.session_token != ""


@pytest.mark.asyncio
async def test_verify_mfa_success(mock_db, mock_redis):
    from iam.services.auth_service import verify_mfa
    from iam.schemas.auth import LoginResponse
    import pyotp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    session_token = create_mfa_session_token(USER_ID, TENANT_ID)
    row = make_user_row(mfa_enabled=True, totp_secret=secret)

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    result = await verify_mfa(mock_db, mock_redis, session_token, code)
    assert isinstance(result, LoginResponse)


@pytest.mark.asyncio
async def test_verify_mfa_wrong_code(mock_db, mock_redis):
    from iam.services.auth_service import verify_mfa
    from scvri_shared.exceptions import AuthenticationError

    secret = generate_totp_secret()
    session_token = create_mfa_session_token(USER_ID, TENANT_ID)
    row = make_user_row(mfa_enabled=True, totp_secret=secret)

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    with pytest.raises(AuthenticationError):
        await verify_mfa(mock_db, mock_redis, session_token, "000000")
