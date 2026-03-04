"""Shipment tracking router."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from visibility.dependencies import TenantDB, TenantID, UserID, require_write_access
from visibility.schemas.shipment import (
    ETAPredictionResponse,
    ShipmentCreate,
    ShipmentKPIResponse,
    ShipmentResponse,
    ShipmentUpdate,
    TrackingEventCreate,
    TrackingEventResponse,
)
from visibility.services import shipment_service

router = APIRouter(prefix="/shipments", tags=["Shipments"])


@router.get("/", response_model=list[ShipmentResponse])
async def list_shipments(
    db: TenantDB,
    tenant_id: TenantID,
    po_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await shipment_service.list_shipments(db, tenant_id, po_id, status, limit, offset)


@router.post(
    "/",
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
async def create_shipment(
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
    body: ShipmentCreate,
):
    return await shipment_service.create_shipment(db, tenant_id, user_id, body)


@router.get("/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    return await shipment_service.get_shipment(db, tenant_id, shipment_id)


@router.patch(
    "/{shipment_id}",
    response_model=ShipmentResponse,
    dependencies=[Depends(require_write_access)],
)
async def update_shipment(
    shipment_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    body: ShipmentUpdate,
):
    return await shipment_service.update_shipment(db, tenant_id, shipment_id, body)


@router.post(
    "/{shipment_id}/tracking-events",
    response_model=TrackingEventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
async def add_tracking_event(
    shipment_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    body: TrackingEventCreate,
):
    # Ensure shipment_id is consistent
    body = body.model_copy(update={"shipment_id": shipment_id})
    return await shipment_service.add_tracking_event(db, tenant_id, body)


@router.get("/{shipment_id}/eta", response_model=ETAPredictionResponse)
async def predict_eta(
    shipment_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    """Rule-based ETA prediction using historical carrier performance data."""
    return await shipment_service.predict_eta(db, tenant_id, shipment_id)


@router.get("/suppliers/{supplier_id}/kpi", response_model=ShipmentKPIResponse)
async def shipment_kpi(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    period_start: Annotated[datetime, Query()],
    period_end: Annotated[datetime, Query()],
):
    return await shipment_service.get_shipment_kpi(
        db, tenant_id, supplier_id, period_start, period_end
    )
