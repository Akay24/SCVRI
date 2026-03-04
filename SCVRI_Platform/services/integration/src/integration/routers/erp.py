"""ERP connection management and sync trigger endpoints."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from integration.dependencies import AdminDep, DbDep, WriteDep
from integration.schemas.erp import (
    ERPConnectionConfig,
    ERPPullRequest,
    ERPSyncResult,
)
from integration.services.erp_service import (
    list_erp_connections,
    sync_erp_entities,
    upsert_erp_connection,
)

router = APIRouter(prefix="/erp", tags=["ERP Connectors"])


@router.get("/connections", summary="List ERP connections for the tenant")
async def list_connections(
    db: DbDep,
    claims: WriteDep,
) -> list[dict[str, Any]]:
    return await list_erp_connections(db, UUID(claims.tenant_id))


@router.post(
    "/connections",
    status_code=status.HTTP_201_CREATED,
    summary="Create or update an ERP connection",
)
async def upsert_connection(
    config: ERPConnectionConfig,
    db: DbDep,
    claims: AdminDep,
) -> dict[str, Any]:
    if str(config.tenant_id) != claims.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot configure ERP connection for another tenant",
        )
    return await upsert_erp_connection(db, config)


@router.post(
    "/sync",
    summary="Trigger an immediate ERP entity pull",
    response_model=ERPSyncResult,
)
async def trigger_sync(
    request: ERPPullRequest,
    db: DbDep,
    claims: WriteDep,
) -> ERPSyncResult:
    if str(request.tenant_id) != claims.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot sync ERP data for another tenant",
        )
    try:
        return await sync_erp_entities(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
