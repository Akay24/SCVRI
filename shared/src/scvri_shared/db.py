"""Database session factory and engine for SCVRI services.

Provides both async (FastAPI) and sync (Alembic / Celery workers) engines.

Usage in FastAPI::

    from scvri_shared.db import get_async_session

    @router.get("/suppliers")
    async def list_suppliers(session: AsyncSession = Depends(get_async_session)):
        ...

Usage in Celery workers::

    from scvri_shared.db import SyncSessionLocal

    with SyncSessionLocal() as session:
        ...
"""
from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from scvri_shared.config import settings


# ---------------------------------------------------------------------------
# Async engine (FastAPI)
# ---------------------------------------------------------------------------
_async_engine = create_async_engine(
    settings.async_database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    echo=settings.db_echo,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ---------------------------------------------------------------------------
# Sync engine (Alembic migrations, Celery workers)
# ---------------------------------------------------------------------------
_sync_engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    echo=settings.db_echo,
)

SyncSessionLocal: sessionmaker[Session] = sessionmaker(
    bind=_sync_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Tenant-scoped session helpers
# ---------------------------------------------------------------------------
def _set_tenant_context(connection: Any, tenant_id: str) -> None:
    """Inject Row-Level Security context into a DB connection.

    Must be called at the start of every request/task that touches
    tenant-owned data.  The value propagates through the connection
    for the lifetime of the current transaction.
    """
    connection.execute(
        text("SET LOCAL scvri.tenant_id = :tid"),
        {"tid": tenant_id},
    )


async def _async_set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text("SET LOCAL scvri.tenant_id = :tid"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# FastAPI dependency — get async session with tenant context
# ---------------------------------------------------------------------------
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency — yields a raw session WITHOUT tenant context.

    For tenant-scoped endpoints use ``get_tenant_session`` below.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Context manager — async session with RLS tenant context pre-set.

    Usage::

        async with tenant_session(tenant_id) as session:
            results = await session.execute(select(Supplier))
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await _async_set_tenant_context(session, tenant_id)
            yield session


@contextmanager
def sync_tenant_session(tenant_id: str) -> Generator[Session, None, None]:
    """Context manager — sync session with RLS tenant context pre-set.

    Usage::

        with sync_tenant_session(tenant_id) as session:
            session.add(...)
    """
    with SyncSessionLocal() as session:
        with session.begin():
            session.execute(
                text("SET LOCAL scvri.tenant_id = :tid"),
                {"tid": tenant_id},
            )
            yield session


# ---------------------------------------------------------------------------
# Alembic / test helper — raw sync engine accessor
# ---------------------------------------------------------------------------
def get_sync_engine() -> Any:
    return _sync_engine


def get_async_engine() -> Any:
    return _async_engine


# ---------------------------------------------------------------------------
# Convenience aliases — backwards-compat names used across services
# ---------------------------------------------------------------------------

# FastAPI dependency — yields an unscoped (public) async session
get_public_session = get_async_session

# Alias: tenant_session is itself the context-manager dep used as
# ``async with get_tenant_session(tenant_id) as session``
get_tenant_session = tenant_session

# Alias: sync engine accessor
get_engine = get_sync_engine

# Alias: async session dep used directly in Annotated hints
get_db = get_async_session
get_async_db = get_async_session

# Annotated convenience type for FastAPI route signatures
from typing import Annotated  # noqa: E402
from fastapi import Depends  # noqa: E402

AsyncSessionDep = Annotated[AsyncSession, Depends(get_async_session)]

