"""Suppliers router — main CRUD, search, bulk ops, PII endpoint, CSV export."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from fastapi.responses import StreamingResponse

from scvri_shared.db import AsyncSessionDep
from scvri_shared.schemas import OperationResult, PaginatedResponse, PaginationMeta
from supplier_management.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    UserRole,
    require_pii_access,
    require_write_access,
)
from supplier_management.schemas.supplier import (
    BulkSupplierStatusUpdate,
    CertificationCreate,
    CertificationResponse,
    OnboardingTransitionRequest,
    SupplierCreate,
    SupplierResponse,
    SupplierSearchRequest,
    SupplierSummary,
    SupplierUpdate,
)
from supplier_management.services import supplier_service

router = APIRouter()


# ---------------------------------------------------------------------------
# List / Search
# ---------------------------------------------------------------------------
@router.get("/", response_model=PaginatedResponse[SupplierSummary])
async def list_suppliers(
    db: TenantDB,
    tenant_id: TenantID,
    # Search / filter params (bound as Query)
    query: str | None = Query(None, description="Full-text search query"),
    status: list[str] | None = Query(None),
    tier: list[str] | None = Query(None),
    onboarding_status: list[str] | None = Query(None),
    country_codes: list[str] | None = Query(None),
    tags: list[str] | None = Query(None),
    is_mbe: bool | None = Query(None),
    is_wbe: bool | None = Query(None),
    is_veteran_owned: bool | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    req = SupplierSearchRequest(
        query=query,
        status=status,
        tier=tier,
        onboarding_status=onboarding_status,
        country_codes=country_codes,
        tags=tags,
        is_mbe=is_mbe,
        is_wbe=is_wbe,
        is_veteran_owned=is_veteran_owned,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    suppliers, total = await supplier_service.search_suppliers(db, tenant_id, req)
    summaries = [SupplierSummary.model_validate(s) for s in suppliers]
    return PaginatedResponse(
        data=summaries,
        pagination=PaginationMeta(page=page, page_size=page_size, total_items=total),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@router.post("/", response_model=SupplierResponse, status_code=201,
             dependencies=[Depends(require_write_access)])
async def create_supplier(
    body: SupplierCreate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    supplier = await supplier_service.create_supplier(db, tenant_id, user_id, body)
    await db.commit()
    await db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


# ---------------------------------------------------------------------------
# Get single supplier
# ---------------------------------------------------------------------------
@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    supplier = await supplier_service.get_supplier(db, tenant_id, supplier_id)
    return SupplierResponse.model_validate(supplier)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
@router.put("/{supplier_id}", response_model=SupplierResponse,
            dependencies=[Depends(require_write_access)])
async def update_supplier(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    supplier = await supplier_service.update_supplier(db, tenant_id, supplier_id, user_id, body)
    await db.commit()
    await db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------
@router.delete("/{supplier_id}", status_code=204,
               dependencies=[Depends(require_write_access)])
async def delete_supplier(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    await supplier_service.soft_delete_supplier(db, tenant_id, supplier_id, user_id)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# PII endpoint — returns tax_id
# ---------------------------------------------------------------------------
@router.get("/{supplier_id}/pii",
            dependencies=[Depends(require_pii_access)])
async def get_supplier_pii(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    supplier = await supplier_service.get_supplier(db, tenant_id, supplier_id)
    return {"supplier_id": str(supplier.id), "tax_id": supplier.tax_id}


# ---------------------------------------------------------------------------
# Bulk status update
# ---------------------------------------------------------------------------
@router.post("/bulk-status", response_model=OperationResult,
             dependencies=[Depends(require_write_access)])
async def bulk_update_status(
    body: BulkSupplierStatusUpdate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    count = await supplier_service.bulk_update_status(db, tenant_id, user_id, body)
    await db.commit()
    return OperationResult(
        success=True,
        message=f"Updated {count} suppliers to status '{body.status}'",
        affected_count=count,
    )


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------
@router.get("/export", summary="Export all suppliers as CSV",
            dependencies=[Depends(require_write_access)])
async def export_csv(
    db: TenantDB,
    tenant_id: TenantID,
):
    csv_bytes = await supplier_service.export_suppliers_csv(db, tenant_id)
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=suppliers.csv"},
    )


# ---------------------------------------------------------------------------
# Certifications (nested under suppliers for simplicity)
# ---------------------------------------------------------------------------
@router.get("/{supplier_id}/certifications", response_model=list[CertificationResponse])
async def list_certifications(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    certs = await supplier_service.list_certifications(db, tenant_id, supplier_id)
    return [CertificationResponse.model_validate(c) for c in certs]


@router.post("/{supplier_id}/certifications", response_model=CertificationResponse,
             status_code=201, dependencies=[Depends(require_write_access)])
async def create_certification(
    supplier_id: uuid.UUID,
    body: CertificationCreate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    cert = await supplier_service.create_certification(db, tenant_id, supplier_id, user_id, body)
    await db.commit()
    await db.refresh(cert)
    return CertificationResponse.model_validate(cert)
