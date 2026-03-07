"""JWT token claims and auth utilities shared across SCVRI services.

Services should import ``TokenClaims`` from here rather than defining
their own copies::

    from scvri_shared.auth import TokenClaims
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from scvri_shared.security import verify_access_token

_bearer = HTTPBearer(auto_error=True)


class TokenClaims:
    """Parsed and validated JWT access-token claims."""

    __slots__ = ("user_id", "tenant_id", "role", "email", "jti")

    def __init__(self, claims: dict) -> None:
        self.user_id: str = claims["sub"]
        self.tenant_id: str = claims["tenant_id"]
        self.role: str = claims["role"]
        self.email: str = claims.get("email", "")
        self.jti: str = claims["jti"]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> TokenClaims:
    """FastAPI dependency — validates Bearer token and returns TokenClaims."""
    try:
        claims = verify_access_token(credentials.credentials)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    if claims.get("token_type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    return TokenClaims(claims)


# Convenience type alias for use in Annotated hints
CurrentUser = Annotated[TokenClaims, Depends(get_current_user)]
