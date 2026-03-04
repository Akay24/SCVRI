"""Auth router — login, MFA, token refresh, TOTP setup, password reset."""
from __future__ import annotations

import uuid
from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from iam.dependencies import (
    AdminDep,
    CurrentUserDep,
    TenantDbDep,
    WriteDep,
    get_redis,
    get_tenant_db_from_token,
)
from iam.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MFAChallengeResponse,
    MFAVerifyRequest,
    PasswordResetConfirm,
    PasswordResetRequestIn,
    TOTPDisableRequest,
    TOTPSetupResponse,
    TOTPVerifyRequest,
    TokenRefreshRequest,
    TokenRefreshResponse,
)
from iam.services import auth_service, user_service
from scvri_shared.database import get_tenant_session
from scvri_shared.exceptions import AuthenticationError

import redis.asyncio as aioredis

router = APIRouter(prefix="/auth", tags=["auth"])

RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post(
    "/login",
    response_model=Union[LoginResponse, MFAChallengeResponse],
    summary="Authenticate with email + password",
)
async def login(
    data: LoginRequest,
    request: Request,
    redis: RedisDep,
) -> Union[LoginResponse, MFAChallengeResponse]:
    """
    Step 1 of authentication.
    - Returns LoginResponse if MFA is not enabled.
    - Returns MFAChallengeResponse if TOTP is required.
    """
    # Resolve tenant DB — use public schema to look up tenant from email domain
    from scvri_shared.database import get_public_session  # noqa: PLC0415

    async with get_public_session() as db:
        try:
            return await auth_service.authenticate_user(
                db, redis, data.email, data.password, data.tenant_id
            )
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post(
    "/mfa/verify",
    response_model=LoginResponse,
    summary="Complete MFA — verify TOTP code",
)
async def verify_mfa(
    data: MFAVerifyRequest,
    redis: RedisDep,
) -> LoginResponse:
    from scvri_shared.database import get_public_session  # noqa: PLC0415

    async with get_public_session() as db:
        try:
            return await auth_service.verify_mfa(db, redis, data.session_token, data.code)
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    summary="Rotate refresh token",
)
async def refresh(
    data: TokenRefreshRequest,
    redis: RedisDep,
) -> TokenRefreshResponse:
    from scvri_shared.database import get_public_session  # noqa: PLC0415

    async with get_public_session() as db:
        try:
            return await auth_service.refresh_tokens(db, redis, data.refresh_token)
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke tokens")
async def logout(
    claims: CurrentUserDep,
    redis: RedisDep,
    data: TokenRefreshRequest | None = None,
) -> None:
    refresh_tok = data.refresh_token if data else None
    await auth_service.logout(redis, claims.jti, refresh_tok)


@router.get("/me", response_model=dict, summary="Current user info")
async def me(claims: CurrentUserDep) -> dict:
    return {
        "user_id": str(claims.user_id),
        "tenant_id": str(claims.tenant_id),
        "role": claims.role,
        "email": claims.email,
    }


# ── TOTP setup ────────────────────────────────────────────────────────────────

@router.post(
    "/totp/setup",
    response_model=TOTPSetupResponse,
    summary="Initiate TOTP MFA setup",
)
async def setup_totp(
    claims: CurrentUserDep,
    db: TenantDbDep,
) -> TOTPSetupResponse:
    return await auth_service.setup_totp(db, claims.user_id)


@router.post(
    "/totp/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm TOTP setup with first valid code",
)
async def confirm_totp(
    data: TOTPVerifyRequest,
    claims: CurrentUserDep,
    db: TenantDbDep,
) -> None:
    try:
        await auth_service.confirm_totp_setup(db, claims.user_id, data.code)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete(
    "/totp",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable TOTP MFA",
)
async def disable_totp(
    data: TOTPDisableRequest,
    claims: CurrentUserDep,
    db: TenantDbDep,
) -> None:
    try:
        await auth_service.disable_totp(db, claims.user_id, data.current_password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── Password reset ─────────────────────────────────────────────────────────────

@router.post(
    "/password/reset-request",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Request password reset email",
)
async def password_reset_request(data: PasswordResetRequestIn) -> None:
    """
    Silently accepted — no 404 if email unknown (prevents user enumeration).
    In production the token would be emailed; here it is discarded.
    """
    from scvri_shared.database import get_public_session  # noqa: PLC0415

    async with get_public_session() as db:
        await auth_service.request_password_reset(db, data.email)


@router.post(
    "/password/reset-confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Apply new password using reset token",
)
async def password_reset_confirm(data: PasswordResetConfirm) -> None:
    from scvri_shared.database import get_public_session  # noqa: PLC0415

    async with get_public_session() as db:
        try:
            await auth_service.confirm_password_reset(db, data.token, data.new_password)
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
