"""FastAPI dependencies for the Visibility service."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from scvri_shared.config import settings

# ── Roles ─────────────────────────────────────────────────────────────────────

ROLES_WITH_WRITE_ACCESS: frozenset[str] = frozenset(
    {"supply_chain_manager", "procurement_officer", "it_administrator", "logistics_coordinator"}
)

# ── DB engine (module-level singleton) ────────────────────────────────────────

_engine = create_async_engine(
    str(settings.database_url),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
)
_async_session = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with _async_session() as session:
        yield session


# ── Tenant-scoped DB ──────────────────────────────────────────────────────────

async def get_tenant_db(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:  # type: ignore[return]
    tenant_id: uuid.UUID = request.state.tenant_id
    await db.execute(text(f"SET LOCAL scvri.tenant_id = '{tenant_id}'"))
    yield db


# ── Request metadata shortcuts ────────────────────────────────────────────────

def get_tenant_id(request: Request) -> uuid.UUID:
    return request.state.tenant_id


def get_user_id(request: Request) -> uuid.UUID:
    return request.state.user_id


def get_user_role(request: Request) -> str:
    return request.state.role


# ── Role guards ───────────────────────────────────────────────────────────────

async def require_write_access(request: Request) -> None:
    role: str = request.state.role
    if role not in ROLES_WITH_WRITE_ACCESS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' does not have write access to the Visibility service",
        )


# ── Type aliases ──────────────────────────────────────────────────────────────

TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
TenantID = Annotated[uuid.UUID, Depends(get_tenant_id)]
UserID = Annotated[uuid.UUID, Depends(get_user_id)]
UserRole = Annotated[str, Depends(get_user_role)]
