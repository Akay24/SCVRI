"""FastAPI dependency injection — DB session, current user, RBAC guards."""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from iam.core.security import decode_access_token, is_token_revoked
from scvri_shared.config import settings
from scvri_shared.database import get_tenant_session
from scvri_shared.logging import get_logger

log = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

# ── Role constants ─────────────────────────────────────────────────────────────

ADMIN_ROLES = {"it_administrator"}
WRITE_ROLES = {"it_administrator", "supply_chain_manager", "procurement_officer", "risk_analyst"}


# ── Redis client  ─────────────────────────────────────────────────────────────

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    return _redis_client


# ── DB session ────────────────────────────────────────────────────────────────

async def get_db(tenant_id: uuid.UUID) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[return]
    async with get_tenant_session(tenant_id) as session:
        yield session


# ── Token extraction + validation ─────────────────────────────────────────────

class TokenClaims:
    """Validated claims attached to the request."""
    def __init__(self, claims: dict):
        self.user_id: uuid.UUID = uuid.UUID(claims["sub"])
        self.tenant_id: uuid.UUID = uuid.UUID(claims.get("tenant_id") or claims["tid"])
        self.role: str = claims["role"]
        self.email: str = claims["email"]
        self.jti: str = claims["jti"]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> TokenClaims:
    """Extract and validate bearer token; return parsed claims."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exc

    try:
        claims = decode_access_token(credentials.credentials)
    except JWTError:
        raise credentials_exc

    if claims.get("token_type") != "access":
        raise credentials_exc

    if await is_token_revoked(redis, claims.get("jti", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenClaims(claims)


async def get_tenant_db_from_token(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[return]
    async with get_tenant_session(claims.tenant_id) as session:
        yield session


TenantDbDep = Annotated[AsyncSession, Depends(get_tenant_db_from_token)]
CurrentUserDep = Annotated[TokenClaims, Depends(get_current_user)]


# ── RBAC guards ───────────────────────────────────────────────────────────────

async def require_admin(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
) -> TokenClaims:
    if claims.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required",
        )
    return claims


async def require_write(
    claims: Annotated[TokenClaims, Depends(get_current_user)],
) -> TokenClaims:
    if claims.role not in WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims


AdminDep = Annotated[TokenClaims, Depends(require_admin)]
WriteDep = Annotated[TokenClaims, Depends(require_write)]
