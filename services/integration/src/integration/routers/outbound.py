"""Outbound push endpoint management and manual push trigger."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from integration.dependencies import AdminDep, DbDep, OutboundRLDep, WriteDep
from integration.schemas.outbound import (
    OutboundEndpoint,
    OutboundPushRequest,
    OutboundPushResult,
)
from integration.services.outbound_service import (
    create_endpoint,
    delete_endpoint,
    list_delivery_attempts,
    list_endpoints,
    push_event,
)

router = APIRouter(prefix="/outbound", tags=["Outbound Push"])


@router.get("/endpoints", summary="List outbound webhook endpoints")
async def list_outbound_endpoints(
    db: DbDep,
    claims: WriteDep,
) -> list[OutboundEndpoint]:
    return await list_endpoints(db, UUID(claims.tenant_id))


@router.post(
    "/endpoints",
    status_code=status.HTTP_201_CREATED,
    summary="Register an outbound webhook endpoint",
)
async def create_outbound_endpoint(
    endpoint: OutboundEndpoint,
    db: DbDep,
    claims: AdminDep,
) -> OutboundEndpoint:
    if str(endpoint.tenant_id) != claims.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    return await create_endpoint(db, endpoint)


@router.delete(
    "/endpoints/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an outbound endpoint",
)
async def delete_outbound_endpoint(
    endpoint_id: UUID,
    db: DbDep,
    claims: AdminDep,
) -> None:
    deleted = await delete_endpoint(db, endpoint_id, UUID(claims.tenant_id))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")


@router.post(
    "/push",
    summary="Manually trigger an outbound push event",
    response_model=OutboundPushResult,
)
async def trigger_push(
    request: OutboundPushRequest,
    db: DbDep,
    rate_limiter: OutboundRLDep,
    claims: WriteDep,
) -> OutboundPushResult:
    if str(request.tenant_id) != claims.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    return await push_event(db, rate_limiter, request)


@router.get("/attempts", summary="List outbound delivery attempts for the tenant")
async def list_attempts(
    db: DbDep,
    claims: WriteDep,
    endpoint_id: UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return await list_delivery_attempts(
        db,
        tenant_id=UUID(claims.tenant_id),
        endpoint_id=endpoint_id,
        limit=limit,
    )
