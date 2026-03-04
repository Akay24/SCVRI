"""Scorecards router — create, list, get single, and trend endpoint."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query

from scvri_shared.schemas import PaginatedResponse, PaginationMeta
from supplier_management.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    require_write_access,
)
from supplier_management.schemas.scorecard import (
    ScorecardCreate,
    ScorecardResponse,
    ScorecardTrendResponse,
)
from supplier_management.services import scorecard_service

router = APIRouter()


@router.get(
    "/{supplier_id}/scorecards",
    response_model=PaginatedResponse[ScorecardResponse],
)
async def list_scorecards(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    scorecards, total = await scorecard_service.list_scorecards(
        db, tenant_id, supplier_id, page, page_size
    )
    return PaginatedResponse(
        data=[ScorecardResponse.model_validate(s) for s in scorecards],
        pagination=PaginationMeta(page=page, page_size=page_size, total_items=total),
    )


@router.get(
    "/{supplier_id}/scorecards/trend",
    response_model=ScorecardTrendResponse,
    summary="Time-series trend data for up to the last 12 scorecard periods.",
)
async def get_scorecard_trend(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
    limit: int = Query(12, ge=1, le=24),
):
    return await scorecard_service.get_scorecard_trend(
        db, tenant_id, supplier_id, period_start, period_end, limit
    )


@router.get(
    "/{supplier_id}/scorecards/{scorecard_id}",
    response_model=ScorecardResponse,
)
async def get_scorecard(
    supplier_id: uuid.UUID,
    scorecard_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    sc = await scorecard_service.get_scorecard(db, tenant_id, supplier_id, scorecard_id)
    return ScorecardResponse.model_validate(sc)


@router.post(
    "/{supplier_id}/scorecards",
    response_model=ScorecardResponse,
    status_code=201,
    dependencies=[Depends(require_write_access)],
    summary="Manually submit a scorecard for a period.",
)
async def create_scorecard(
    supplier_id: uuid.UUID,
    body: ScorecardCreate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    sc = await scorecard_service.create_scorecard(db, tenant_id, supplier_id, user_id, body)
    await db.commit()
    await db.refresh(sc)
    return ScorecardResponse.model_validate(sc)
