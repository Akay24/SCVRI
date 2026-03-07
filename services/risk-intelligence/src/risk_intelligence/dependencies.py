"""Risk Intelligence service — dependency injection helpers."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.db import get_async_db
from scvri_shared.exceptions import ForbiddenError

# Role sets
ROLES_WITH_WRITE_ACCESS = frozenset({
    "supply_chain_manager", "procurement_officer", "it_administrator", "risk_analyst"
})
ROLES_WITH_ML_ADMIN = frozenset({"ml_lead", "it_administrator"})


# ---------------------------------------------------------------------------
# State extractors
# ---------------------------------------------------------------------------
def get_tenant_id(request: Request) -> uuid.UUID:
    return request.state.tenant_id


def get_user_id(request: Request) -> uuid.UUID:
    return request.state.user_id


def get_user_role(request: Request) -> str:
    return request.state.role


# ---------------------------------------------------------------------------
# Tenant-scoped DB session — sets RLS context variable
# ---------------------------------------------------------------------------
async def get_tenant_db(
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_async_db),
) -> AsyncSession:
    from sqlalchemy import text  # noqa: PLC0415
    await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})
    return db


# ---------------------------------------------------------------------------
# Role gates
# ---------------------------------------------------------------------------
def require_role(*allowed_roles: str):
    def _check(role: str = Depends(get_user_role)):
        if role not in allowed_roles:
            raise ForbiddenError(action="access", resource="risk-intelligence")
    return Depends(_check)


def require_write_access(role: str = Depends(get_user_role)) -> None:
    if role not in ROLES_WITH_WRITE_ACCESS:
        raise ForbiddenError(action="write", resource="risk-intelligence")


def require_ml_admin(role: str = Depends(get_user_role)) -> None:
    if role not in ROLES_WITH_ML_ADMIN:
        raise ForbiddenError(action="ml_admin", resource="model-registry")


# ---------------------------------------------------------------------------
# Type aliases for router signatures
# ---------------------------------------------------------------------------
TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
TenantID = Annotated[uuid.UUID, Depends(get_tenant_id)]
UserID = Annotated[uuid.UUID, Depends(get_user_id)]
UserRole = Annotated[str, Depends(get_user_role)]
