"""Backwards-compatibility shim — ``scvri_shared.database``.

All symbols were moved to ``scvri_shared.db``.  Import from there directly;
this module exists only to avoid breaking existing service code that was
written against the old layout.
"""
from scvri_shared.db import (  # noqa: F401
    AsyncSessionDep,
    AsyncSessionLocal,
    SyncSessionLocal,
    get_async_db,
    get_async_engine,
    get_async_session,
    get_db,
    get_engine,
    get_public_session,
    get_sync_engine,
    get_tenant_session,
    sync_tenant_session,
    tenant_session,
)
