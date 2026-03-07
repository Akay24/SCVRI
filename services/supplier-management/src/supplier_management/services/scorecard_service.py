"""Scorecard service — compute, persist, and trend supplier performance scorecards.

Scoring formula (SCOR-aligned):
  OTD (On-Time Delivery) rate  = on_time_deliveries / total_deliveries        × 35%
  Fill Rate                    = quantity_received / quantity_ordered          × 25%
  Defect Rate                  = quantity_returned / quantity_received         × 25% (inverted)
  Invoice Accuracy             = (1 - invoice_disputes / invoices_raised)      × 15%

  overall_score = sum of weighted components  (0-100)
  grade: A (≥85), B (≥70), C (≥55), D (<55)
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError
from scvri_shared.logging import get_logger
from scvri_shared.models.supplier import SupplierScorecard
from supplier_management.schemas.scorecard import (
    ScorecardCreate,
    ScorecardResponse,
    ScorecardTrendPoint,
    ScorecardTrendResponse,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Compute helpers
# ---------------------------------------------------------------------------
def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _compute_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _compute_overall(
    otd_rate: float,
    fill_rate: float,
    defect_rate: float,
    invoice_accuracy: float,
) -> float:
    """Compute weighted overall score (0-100)."""
    score = (
        (otd_rate * 0.35)
        + (fill_rate * 0.25)
        + ((100 - defect_rate) * 0.25)   # lower defects → higher score
        + (invoice_accuracy * 0.15)
    )
    return round(max(0.0, min(100.0, score)), 2)


# ---------------------------------------------------------------------------
# Create scorecard
# ---------------------------------------------------------------------------
async def create_scorecard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ScorecardCreate,
) -> SupplierScorecard:
    """Persist a new scorecard period for a supplier."""
    from supplier_management.services.supplier_service import get_supplier  # noqa: PLC0415
    await get_supplier(db, tenant_id, supplier_id)

    otd_rate = _safe_rate(data.on_time_deliveries, data.total_deliveries)
    fill_rate = _safe_rate(data.quantity_received, data.quantity_ordered)
    defect_rate = _safe_rate(data.quantity_returned, data.quantity_received)
    invoice_disputes = data.invoice_disputes or 0
    invoices_raised = data.invoices_raised or 0
    invoice_accuracy = _safe_rate(invoices_raised - invoice_disputes, invoices_raised)
    overall_score = _compute_overall(otd_rate, fill_rate, defect_rate, invoice_accuracy)
    grade = _compute_grade(overall_score)

    scorecard = SupplierScorecard(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        period_start=data.period_start,
        period_end=data.period_end,
        # Delivery
        total_deliveries=data.total_deliveries,
        on_time_deliveries=data.on_time_deliveries,
        otd_rate=otd_rate,
        # Quality
        quantity_ordered=data.quantity_ordered,
        quantity_received=data.quantity_received,
        quantity_returned=data.quantity_returned,
        fill_rate=fill_rate,
        defect_rate=defect_rate,
        # Invoicing
        invoices_raised=invoices_raised,
        invoice_disputes=invoice_disputes,
        invoice_accuracy_rate=invoice_accuracy,
        # Responsiveness (optional)
        avg_response_time_hours=data.avg_response_time_hours,
        ncr_count=data.ncr_count,
        # Computed
        overall_score=overall_score,
        grade=grade,
        notes=data.notes,
        assessed_by=user_id,
    )
    db.add(scorecard)
    await db.flush()

    log.info(
        "scorecard.created",
        supplier_id=str(supplier_id),
        period_start=str(data.period_start),
        overall_score=overall_score,
        grade=grade,
    )
    return scorecard


# ---------------------------------------------------------------------------
# Get scorecard
# ---------------------------------------------------------------------------
async def get_scorecard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    scorecard_id: uuid.UUID,
) -> SupplierScorecard:
    result = await db.execute(
        select(SupplierScorecard).where(
            SupplierScorecard.id == scorecard_id,
            SupplierScorecard.supplier_id == supplier_id,
        )
    )
    sc = result.scalar_one_or_none()
    if sc is None:
        raise NotFoundError("scorecard", str(scorecard_id))
    return sc


async def get_latest_scorecard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> SupplierScorecard | None:
    result = await db.execute(
        select(SupplierScorecard)
        .where(SupplierScorecard.supplier_id == supplier_id)
        .order_by(desc(SupplierScorecard.period_end))
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Trend data
# ---------------------------------------------------------------------------
async def get_scorecard_trend(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    period_start: date | None = None,
    period_end: date | None = None,
    limit: int = 12,
) -> ScorecardTrendResponse:
    """Return time-series trend of scorecard metrics."""
    from supplier_management.services.supplier_service import get_supplier  # noqa: PLC0415
    await get_supplier(db, tenant_id, supplier_id)

    stmt = (
        select(SupplierScorecard)
        .where(SupplierScorecard.supplier_id == supplier_id)
        .order_by(desc(SupplierScorecard.period_end))
        .limit(limit)
    )
    if period_start:
        stmt = stmt.where(SupplierScorecard.period_start >= period_start)
    if period_end:
        stmt = stmt.where(SupplierScorecard.period_end <= period_end)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    points = [
        ScorecardTrendPoint(
            period_start=sc.period_start,
            period_end=sc.period_end,
            overall_score=sc.overall_score,
            otd_rate=sc.otd_rate,
            fill_rate=sc.fill_rate,
            defect_rate=sc.defect_rate,
            invoice_accuracy_rate=sc.invoice_accuracy_rate,
            grade=sc.grade,
        )
        for sc in reversed(rows)  # oldest first
    ]
    return ScorecardTrendResponse(supplier_id=supplier_id, data_points=points)


# ---------------------------------------------------------------------------
# List scorecards
# ---------------------------------------------------------------------------
async def list_scorecards(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SupplierScorecard], int]:
    from sqlalchemy import func  # noqa: PLC0415

    count = (await db.execute(
        select(func.count(SupplierScorecard.id))
        .where(SupplierScorecard.supplier_id == supplier_id)
    )).scalar_one()

    result = await db.execute(
        select(SupplierScorecard)
        .where(SupplierScorecard.supplier_id == supplier_id)
        .order_by(desc(SupplierScorecard.period_end))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), count
