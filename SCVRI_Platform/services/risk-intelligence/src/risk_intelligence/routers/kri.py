"""KRI router — definitions, snapshots, and per-supplier dashboard."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from risk_intelligence.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    require_write_access,
)
from risk_intelligence.schemas.kri import (
    KRIDefinitionCreate,
    KRIDefinitionResponse,
    KRISnapshotCreate,
    KRISnapshotResponse,
    SupplierKRIDashboard,
)
from risk_intelligence.services import kri_service

router = APIRouter()


# ---------------------------------------------------------------------------
# KRI Definitions
# ---------------------------------------------------------------------------
@router.get("/kri/definitions", response_model=list[KRIDefinitionResponse])
async def list_kri_definitions(
    db: TenantDB,
    tenant_id: TenantID,
):
    defs = await kri_service.list_kri_definitions(db, tenant_id)
    return [KRIDefinitionResponse.model_validate(d) for d in defs]


@router.post(
    "/kri/definitions",
    response_model=KRIDefinitionResponse,
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
async def create_kri_definition(
    body: KRIDefinitionCreate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    defn = await kri_service.create_kri_definition(db, tenant_id, user_id, body)
    await db.commit()
    await db.refresh(defn)
    return KRIDefinitionResponse.model_validate(defn)


@router.get("/kri/definitions/{kri_id}", response_model=KRIDefinitionResponse)
async def get_kri_definition(
    kri_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    defn = await kri_service.get_kri_definition(db, tenant_id, kri_id)
    return KRIDefinitionResponse.model_validate(defn)


# ---------------------------------------------------------------------------
# KRI Snapshots
# ---------------------------------------------------------------------------
@router.post(
    "/kri/snapshots",
    response_model=KRISnapshotResponse,
    status_code=201,
    dependencies=[Depends(require_write_access)],
    summary="Record a KRI measurement for a supplier.",
)
async def record_snapshot(
    body: KRISnapshotCreate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    snap = await kri_service.record_kri_snapshot(db, tenant_id, user_id, body)
    defn = await kri_service.get_kri_definition(db, tenant_id, body.kri_definition_id)
    await db.commit()
    return KRISnapshotResponse(
        id=snap.id,
        supplier_id=snap.supplier_id,
        kri_definition_id=snap.kri_definition_id,
        kri_name=defn.name,
        category=defn.category,
        value=snap.value,
        status=snap.status,
        unit=defn.unit,
        measured_at=snap.measured_at,
    )


# ---------------------------------------------------------------------------
# Per-supplier KRI dashboard
# ---------------------------------------------------------------------------
@router.get(
    "/{supplier_id}/kri/dashboard",
    response_model=SupplierKRIDashboard,
    summary="All latest KRI readings for a supplier, grouped with RAG counts.",
)
async def get_supplier_kri_dashboard(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    return await kri_service.get_supplier_kri_dashboard(db, tenant_id, supplier_id)
