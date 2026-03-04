"""FastAPI dependency providers for the Integration service."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from integration.core.rate_limiter import (
    OUTBOUND_RATE_LIMIT,
    OUTBOUND_RATE_WINDOW,
    SlidingWindowRateLimiter,
    WEBHOOK_RATE_LIMIT,
    WEBHOOK_RATE_WINDOW,
)
from scvri_shared.config import get_settings

settings = get_settings()

# ── Database ───────────────────────────────────────────────────────────────────
_engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
_AsyncSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with _AsyncSession() as session:
        yield session


# ── Redis ──────────────────────────────────────────────────────────────────────
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=False,
        )
    return _redis


# ── Rate limiters ──────────────────────────────────────────────────────────────

async def get_webhook_rate_limiter(
    redis: aioredis.Redis = Depends(get_redis),
) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(
        redis,
        limit=WEBHOOK_RATE_LIMIT,
        window=WEBHOOK_RATE_WINDOW,
        prefix="rl:webhook",
    )


async def get_outbound_rate_limiter(
    redis: aioredis.Redis = Depends(get_redis),
) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(
        redis,
        limit=OUTBOUND_RATE_LIMIT,
        window=OUTBOUND_RATE_WINDOW,
        prefix="rl:outbound",
    )


# ── JWT auth (verify with IAM RS256 public key) ────────────────────────────────
_bearer = HTTPBearer(auto_error=True)


@lru_cache(maxsize=1)
def _get_public_key() -> str:
    """Load IAM RS256 public key for JWT verification."""
    import os
    key = os.getenv("IAM_PUBLIC_KEY")
    if key:
        return key.replace("\\n", "\n")
    key_path = os.getenv("IAM_PUBLIC_KEY_PATH")
    if key_path:
        with open(key_path) as f:
            return f.read()
    raise RuntimeError("IAM public key not configured (IAM_PUBLIC_KEY or IAM_PUBLIC_KEY_PATH)")


class TokenClaims:
    __slots__ = ("user_id", "tenant_id", "role", "email", "jti")

    def __init__(self, claims: dict) -> None:
        self.user_id: str = claims["sub"]
        self.tenant_id: str = claims["tenant_id"]
        self.role: str = claims["role"]
        self.email: str = claims["email"]
        self.jti: str = claims["jti"]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> TokenClaims:
    try:
        claims = jwt.decode(
            credentials.credentials,
            _get_public_key(),
            algorithms=["RS256"],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    if claims.get("token_type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    return TokenClaims(claims)


ADMIN_ROLES = {"it_administrator"}
WRITE_ROLES = {"it_administrator", "supply_chain_manager", "procurement_officer", "risk_analyst"}


async def require_admin(claims: TokenClaims = Depends(get_current_user)) -> TokenClaims:
    if claims.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return claims


async def require_write(claims: TokenClaims = Depends(get_current_user)) -> TokenClaims:
    if claims.role not in WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write access required")
    return claims


# Type aliases
DbDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[TokenClaims, Depends(get_current_user)]
AdminDep = Annotated[TokenClaims, Depends(require_admin)]
WriteDep = Annotated[TokenClaims, Depends(require_write)]
WebhookRLDep = Annotated[SlidingWindowRateLimiter, Depends(get_webhook_rate_limiter)]
OutboundRLDep = Annotated[SlidingWindowRateLimiter, Depends(get_outbound_rate_limiter)]
