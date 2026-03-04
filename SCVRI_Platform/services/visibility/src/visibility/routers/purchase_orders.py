"""Purchase Order router — state machine + CRUD."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from visibility.dependencies import TenantDB, TenantID, UserID, require_write_access
from visibility.schemas.purchase_order import (
    PODeliveryMetrics,
    POEventRequest,
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
)
from visibility.services import po_service

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])


@router.get("/", response_model=list[PurchaseOrderResponse])
async def list_pos(
    db: TenantDB,
    tenant_id: TenantID,
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await po_service.list_purchase_orders(db, tenant_id, supplier_id, status, limit, offset)


@router.post(
    "/",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
async def create_po(
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
    body: PurchaseOrderCreate,
):
    return await po_service.create_purchase_order(db, tenant_id, user_id, body)


@router.get("/{po_id}", response_model=PurchaseOrderResponse)
async def get_po(
    po_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    return await po_service.get_purchase_order(db, tenant_id, po_id)


@router.patch(
    "/{po_id}",
    response_model=PurchaseOrderResponse,
    dependencies=[Depends(require_write_access)],
)
async def update_po(
    po_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    body: PurchaseOrderUpdate,
):
    return await po_service.update_purchase_order(db, tenant_id, po_id, body)


@router.post(
    "/{po_id}/events",
    response_model=PurchaseOrderResponse,
    dependencies=[Depends(require_write_access)],
)
async def apply_event(
    po_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
    body: POEventRequest,
):
    """Apply a state-machine event (confirm, ship_partial, receive_complete, etc.)."""
    return await po_service.apply_po_event(db, tenant_id, user_id, po_id, body)


@router.get("/suppliers/{supplier_id}/delivery-metrics", response_model=PODeliveryMetrics)
async def delivery_metrics(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    period_start: Annotated[datetime, Query()],
    period_end: Annotated[datetime, Query()],
):
    return await po_service.get_delivery_metrics(db, tenant_id, supplier_id, period_start, period_end)
