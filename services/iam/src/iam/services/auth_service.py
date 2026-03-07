"""Authentication service — login, token refresh, MFA, password reset."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from iam.core.security import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    create_access_token,
    create_mfa_session_token,
    create_password_reset_token,
    create_refresh_token,
    decode_mfa_session_token,
    decode_password_reset_token,
    decode_refresh_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    build_totp_qr_data_uri,
    hash_password,
    revoke_token,
    store_refresh_token,
    validate_and_rotate_refresh_token,
    verify_password,
    verify_totp,
)
from iam.schemas.auth import (
    LoginResponse,
    MFAChallengeResponse,
    TOTPSetupResponse,
    TokenRefreshResponse,
)
from scvri_shared.exceptions import AuthenticationError, NotFoundError
from scvri_shared.logging import get_logger

log = get_logger(__name__)


# ── Login ─────────────────────────────────────────────────────────────────────

async def authenticate_user(
    db: AsyncSession,
    redis: aioredis.Redis,
    email: str,
    password: str,
    tenant_id: uuid.UUID | None = None,
) -> LoginResponse | MFAChallengeResponse:
    """
    Step 1 of login.
    - Verifies email + password.
    - If MFA is enabled → returns MFAChallengeResponse with a short-lived session_token.
    - Otherwise → issues access + refresh tokens.
    """
    row = await _fetch_user_by_email(db, email, tenant_id)
    if row is None or not verify_password(password, row["password_hash"]):
        raise AuthenticationError("Invalid credentials")

    if row["status"] not in ("active", "pending_mfa"):
        raise AuthenticationError(f"Account is {row['status']}")

    user_id = uuid.UUID(str(row["id"]))
    resolved_tenant_id = uuid.UUID(str(row["tenant_id"]))

    # Update last_login_at
    await db.execute(text("""
        UPDATE iam.users SET last_login_at = now() WHERE id = :id
    """), {"id": str(user_id)})
    await db.commit()

    # MFA gate
    if row["mfa_enabled"]:
        session_token = create_mfa_session_token(user_id, resolved_tenant_id)
        return MFAChallengeResponse(
            mfa_required=True,
            mfa_method="totp",
            session_token=session_token,
        )

    return await _issue_tokens(redis, user_id, resolved_tenant_id, row["role"], row["email"])


async def verify_mfa(
    db: AsyncSession,
    redis: aioredis.Redis,
    session_token: str,
    code: str,
) -> LoginResponse:
    """Step 2 of MFA login — verify TOTP code then issue tokens."""
    try:
        claims = decode_mfa_session_token(session_token)
    except JWTError:
        raise AuthenticationError("Invalid or expired MFA session token")

    user_id = uuid.UUID(claims["sub"])
    tenant_id = uuid.UUID(claims["tenant_id"])

    row = await _fetch_user_by_id(db, user_id)
    if row is None:
        raise AuthenticationError("User not found")

    totp_secret = row.get("totp_secret")
    if not totp_secret or not verify_totp(totp_secret, code):
        raise AuthenticationError("Invalid TOTP code")

    return await _issue_tokens(redis, user_id, tenant_id, row["role"], row["email"])


# ── Token refresh (rotation) ──────────────────────────────────────────────────

async def refresh_tokens(
    db: AsyncSession,
    redis: aioredis.Redis,
    refresh_token: str,
) -> TokenRefreshResponse:
    """Validate old refresh token, rotate it, issue new access + refresh pair."""
    try:
        claims = decode_refresh_token(refresh_token)
    except JWTError:
        raise AuthenticationError("Invalid or expired refresh token")

    old_jti = claims["jti"]
    user_id = uuid.UUID(claims["sub"])
    tenant_id = uuid.UUID(claims["tenant_id"])

    valid = await validate_and_rotate_refresh_token(redis, old_jti, str(user_id))
    if not valid:
        log.warning("token_refresh.invalid_jti", user_id=str(user_id), jti=old_jti)
        raise AuthenticationError("Refresh token has been used or revoked")

    row = await _fetch_user_by_id(db, user_id)
    if row is None or row["status"] != "active":
        raise AuthenticationError("User account unavailable")

    result = await _issue_tokens(redis, user_id, tenant_id, row["role"], row["email"])
    return TokenRefreshResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
    )


# ── Logout ────────────────────────────────────────────────────────────────────

async def logout(
    redis: aioredis.Redis,
    access_jti: str,
    refresh_token: str | None,
) -> None:
    """Revoke access token JTI; optionally revoke refresh token."""
    await revoke_token(redis, access_jti, ACCESS_TOKEN_TTL_SECONDS)
    if refresh_token:
        try:
            claims = decode_refresh_token(refresh_token)
            await redis.delete(f"refresh_token:{claims['jti']}")
        except JWTError:
            pass  # already expired — harmless


# ── TOTP setup ────────────────────────────────────────────────────────────────

async def setup_totp(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> TOTPSetupResponse:
    """Generate a new TOTP secret; store it as pending until confirmed."""
    row = await _fetch_user_by_id(db, user_id)
    if row is None:
        raise NotFoundError("User not found")

    secret = generate_totp_secret()
    uri = get_totp_provisioning_uri(secret, row["email"])
    qr = build_totp_qr_data_uri(uri)

    # Store as pending_totp_secret until verified
    await db.execute(text("""
        UPDATE iam.users
        SET pending_totp_secret = :secret, updated_at = now()
        WHERE id = :id
    """), {"secret": secret, "id": str(user_id)})
    await db.commit()

    return TOTPSetupResponse(secret=secret, provisioning_uri=uri, qr_code_data_uri=qr)


async def confirm_totp_setup(
    db: AsyncSession,
    user_id: uuid.UUID,
    code: str,
) -> None:
    """Verify the first TOTP code and activate MFA for the user."""
    row = await _fetch_user_by_id(db, user_id)
    if row is None:
        raise NotFoundError("User not found")

    pending = row.get("pending_totp_secret")
    if not pending:
        raise AuthenticationError("No pending TOTP setup found")

    if not verify_totp(pending, code):
        raise AuthenticationError("Invalid TOTP code — setup not confirmed")

    await db.execute(text("""
        UPDATE iam.users
        SET totp_secret = :secret,
            pending_totp_secret = NULL,
            mfa_enabled = TRUE,
            mfa_method = 'totp',
            status = 'active',
            updated_at = now()
        WHERE id = :id
    """), {"secret": pending, "id": str(user_id)})
    await db.commit()


async def disable_totp(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_password: str,
) -> None:
    """Disable MFA after re-verifying password."""
    row = await _fetch_user_by_id(db, user_id)
    if row is None:
        raise NotFoundError("User not found")
    if not verify_password(current_password, row["password_hash"]):
        raise AuthenticationError("Incorrect password")

    await db.execute(text("""
        UPDATE iam.users
        SET totp_secret = NULL,
            pending_totp_secret = NULL,
            mfa_enabled = FALSE,
            mfa_method = 'none',
            updated_at = now()
        WHERE id = :id
    """), {"id": str(user_id)})
    await db.commit()


# ── Password reset ─────────────────────────────────────────────────────────────

async def request_password_reset(db: AsyncSession, email: str) -> str | None:
    """
    Generate a reset token.
    Returns the token string (caller is responsible for emailing it).
    Returns None silently if email not found (prevent user enumeration).
    """
    row = (await db.execute(text("""
        SELECT id FROM iam.users WHERE email = :email AND status = 'active'
    """), {"email": email.lower()})).mappings().one_or_none()

    if row is None:
        return None

    return create_password_reset_token(uuid.UUID(str(row["id"])))


async def confirm_password_reset(
    db: AsyncSession,
    token: str,
    new_password: str,
) -> None:
    """Apply new password after validating reset token."""
    try:
        claims = decode_password_reset_token(token)
    except JWTError:
        raise AuthenticationError("Invalid or expired password reset token")

    user_id = uuid.UUID(claims["sub"])
    new_hash = hash_password(new_password)

    await db.execute(text("""
        UPDATE iam.users
        SET password_hash = :hash, updated_at = now()
        WHERE id = :id
    """), {"hash": new_hash, "id": str(user_id)})
    await db.commit()


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_user_by_email(
    db: AsyncSession,
    email: str,
    tenant_id: uuid.UUID | None,
) -> dict | None:
    params: dict = {"email": email.lower()}
    extra = ""
    if tenant_id is not None:
        extra = "AND tenant_id = :tenant_id"
        params["tenant_id"] = str(tenant_id)

    return (await db.execute(text(f"""
        SELECT * FROM iam.users WHERE email = :email {extra} LIMIT 1
    """), params)).mappings().one_or_none()


async def _fetch_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    return (await db.execute(text("""
        SELECT * FROM iam.users WHERE id = :id
    """), {"id": str(user_id)})).mappings().one_or_none()


async def _issue_tokens(
    redis: aioredis.Redis,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    email: str,
) -> LoginResponse:
    access_token, _access_jti = create_access_token(user_id, tenant_id, role, email)
    refresh_token, refresh_jti = create_refresh_token(user_id, tenant_id)
    await store_refresh_token(redis, user_id, refresh_jti)
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_TTL_SECONDS,
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
    )
