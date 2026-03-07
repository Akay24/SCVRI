"""Alerts router — CRUD + lifecycle transitions."""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from alert_engine.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    get_tenant_db,
    require_write_access,
)
from alert_engine.schemas.alert import (
    AlertAcknowledgeRequest,
    AlertCreate,
    AlertEscalateRequest,
    AlertResolveRequest,
    AlertResponse,
    AlertSuppressRequest,
    AlertSummaryResponse,
)
from alert_engine.services import alert_service

router = APIRouter(prefix="/alerts", tags=["alerts"])

DbDep = TenantDB
WriteDep = Annotated[None, Depends(require_write_access)]


@router.get("/summary", response_model=AlertSummaryResponse)
async def get_summary(
    db: DbDep,
    tenant_id: TenantID,
) -> AlertSummaryResponse:
    """Dashboard summary — counts by severity and status."""
    return await alert_service.get_summary(db, tenant_id)


@router.get("/", response_model=list[AlertResponse])
async def list_alerts(
    db: DbDep,
    tenant_id: TenantID,
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    supplier_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[AlertResponse]:
    """List alerts with optional filters."""
    return await alert_service.list_alerts(
        db,
        tenant_id,
        status_filter=status_filter,
        severity=severity,
        source=source,
        supplier_id=supplier_id,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    data: AlertCreate,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: WriteDep,
) -> AlertResponse:
    """Manually create an alert (write access required)."""
    return await alert_service.create_alert(db, tenant_id, user_id, data)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: uuid.UUID,
    db: DbDep,
    tenant_id: TenantID,
) -> AlertResponse:
    return await alert_service.get_alert(db, tenant_id, alert_id)


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    data: AlertAcknowledgeRequest,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: WriteDep,
) -> AlertResponse:
    """Move alert to acknowledged state."""
    return await alert_service.acknowledge_alert(db, tenant_id, alert_id, user_id, data)


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: uuid.UUID,
    data: AlertResolveRequest,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: WriteDep,
) -> AlertResponse:
    """Resolve an alert."""
    return await alert_service.resolve_alert(db, tenant_id, alert_id, user_id, data)


@router.post("/{alert_id}/suppress", response_model=AlertResponse)
async def suppress_alert(
    alert_id: uuid.UUID,
    data: AlertSuppressRequest,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: WriteDep,
) -> AlertResponse:
    """Suppress an alert until a given time."""
    return await alert_service.suppress_alert(db, tenant_id, alert_id, user_id, data)


@router.post("/{alert_id}/escalate", response_model=AlertResponse)
async def escalate_alert(
    alert_id: uuid.UUID,
    data: AlertEscalateRequest,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: WriteDep,
) -> AlertResponse:
    """Manually escalate an alert."""
    return await alert_service.escalate_alert(db, tenant_id, alert_id, user_id, data)
