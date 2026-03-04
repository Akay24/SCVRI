"""Risk scores router — single supplier, bulk, history, and tenant summary."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from scvri_shared.schemas import OperationResult, PaginatedResponse, PaginationMeta
from risk_intelligence.dependencies import TenantDB, TenantID, UserID, require_write_access
from risk_intelligence.schemas.risk_score import (
    BulkRiskScoreRequest,
    RiskScoreHistoryResponse,
    RiskScoreHistoryPoint,
    SupplierRiskScoreRequest,
    SupplierRiskScoreResponse,
    TenantRiskSummaryResponse,
)
from risk_intelligence.services import risk_scoring_service

router = APIRouter()


@router.get("/summary", response_model=TenantRiskSummaryResponse)
async def tenant_risk_summary(
    db: TenantDB,
    tenant_id: TenantID,
):
    """Aggregate risk distribution across all suppliers for this tenant."""
    return await risk_scoring_service.get_tenant_risk_summary(db, tenant_id)


@router.get("/{supplier_id}/risk-score", response_model=SupplierRiskScoreResponse)
async def get_risk_score(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    """Retrieve the latest risk score for a supplier."""
    row = await risk_scoring_service.get_risk_score(db, tenant_id, supplier_id)
    return SupplierRiskScoreResponse(
        id=row.id,
        supplier_id=row.supplier_id,
        tenant_id=row.tenant_id,
        overall_score=row.overall_score,
        risk_level=row.risk_level,
        previous_score=row.previous_score,
        score_delta=row.score_delta,
        components=row.components or [],
        model_id=row.model_id,
        model_version=row.model_version,
        computed_at=row.computed_at,
        valid_until=row.valid_until,
        created_at=row.computed_at,
    )


@router.post(
    "/{supplier_id}/risk-score/compute",
    response_model=SupplierRiskScoreResponse,
    status_code=201,
    dependencies=[Depends(require_write_access)],
    summary="Trigger synchronous risk score computation for one supplier.",
)
async def compute_risk_score(
    supplier_id: uuid.UUID,
    body: SupplierRiskScoreRequest,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    row = await risk_scoring_service.compute_risk_score(
        db, tenant_id, supplier_id, force_recompute=body.force_recompute
    )
    await db.commit()
    await db.refresh(row)
    return SupplierRiskScoreResponse(
        id=row.id,
        supplier_id=row.supplier_id,
        tenant_id=row.tenant_id,
        overall_score=row.overall_score,
        risk_level=row.risk_level,
        previous_score=row.previous_score,
        score_delta=row.score_delta,
        components=row.components or [],
        model_id=row.model_id,
        model_version=row.model_version,
        computed_at=row.computed_at,
        valid_until=row.valid_until,
        created_at=row.computed_at,
    )


@router.get("/{supplier_id}/risk-score/history", response_model=RiskScoreHistoryResponse)
async def get_score_history(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    limit: int = Query(30, ge=1, le=365),
):
    rows = await risk_scoring_service.get_score_history(db, tenant_id, supplier_id, limit)
    points = [
        RiskScoreHistoryPoint(
            overall_score=r.overall_score,
            risk_level=r.risk_level,
            computed_at=r.computed_at,
        )
        for r in reversed(rows)     # oldest first
    ]
    return RiskScoreHistoryResponse(supplier_id=supplier_id, data_points=points)


@router.post(
    "/risk-scores/bulk-compute",
    response_model=OperationResult,
    dependencies=[Depends(require_write_access)],
    summary="Enqueue async risk score computation for up to 200 suppliers.",
)
async def bulk_compute(
    body: BulkRiskScoreRequest,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    task_map = await risk_scoring_service.bulk_compute_risk_scores(
        db, tenant_id, body.supplier_ids, body.force_recompute
    )
    return OperationResult(
        success=True,
        message=f"Enqueued {len(task_map)} risk score computations",
        affected_count=len(task_map),
    )
