"""FastAPI dependency injectors for Supplier Management Service."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.db import get_db
from scvri_shared.exceptions import ForbiddenError, TenantIsolationError


# ---------------------------------------------------------------------------
# Extract validated JWT payload from request state (set by TenantResolutionMiddleware)
# ---------------------------------------------------------------------------
def get_current_user(request: Request) -> dict:
    payload = getattr(request.state, "jwt_payload", None)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return payload


def get_tenant_id(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None)
    if tid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant not resolved.")
    return uuid.UUID(tid)


def get_user_id(request: Request) -> uuid.UUID:
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not resolved.")
    return uuid.UUID(uid)


def get_user_role(request: Request) -> str:
    return getattr(request.state, "role", "")


def get_user_scopes(request: Request) -> list[str]:
    return getattr(request.state, "scopes", [])


# ---------------------------------------------------------------------------
# Role-based access control helpers
# ---------------------------------------------------------------------------
ROLES_WITH_WRITE_ACCESS = {
    "supply_chain_manager",
    "procurement_officer",
    "it_administrator",
}

ROLES_WITH_PII_ACCESS = {
    "compliance_officer",
    "it_administrator",
}

ROLES_WITH_APPROVE_ACCESS = {
    "supply_chain_manager",
    "procurement_officer",
}


def require_role(*allowed_roles: str):
    """Return a FastAPI dependency that asserts the requesting user has one of *allowed_roles*."""
    def _check(role: str = Depends(get_user_role)) -> str:
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' is not authorised for this action.",
            )
        return role
    return _check


def require_write_access(role: str = Depends(get_user_role)) -> str:
    if role not in ROLES_WITH_WRITE_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access requires supply_chain_manager, procurement_officer, or it_administrator role.",
        )
    return role


def require_pii_access(role: str = Depends(get_user_role)) -> str:
    if role not in ROLES_WITH_PII_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PII data access requires compliance_officer or it_administrator role.",
        )
    return role


# ---------------------------------------------------------------------------
# DB session with RLS tenant context
# ---------------------------------------------------------------------------
async def get_tenant_db_session(
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """Return a DB session with PostgreSQL RLS ``scvri.tenant_id`` set."""
    from sqlalchemy import text  # noqa: PLC0415
    await db.execute(
        text("SET LOCAL scvri.tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )
    return db


# ---------------------------------------------------------------------------
# Type aliases for cleaner router signatures
# ---------------------------------------------------------------------------
CurrentUser = Annotated[dict, Depends(get_current_user)]
TenantID = Annotated[uuid.UUID, Depends(get_tenant_id)]
UserID = Annotated[uuid.UUID, Depends(get_user_id)]
UserRole = Annotated[str, Depends(get_user_role)]
TenantDB = Annotated[AsyncSession, Depends(get_tenant_db_session)]
