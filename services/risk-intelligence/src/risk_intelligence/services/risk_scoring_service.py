"""Risk scoring service — compute, persist, and retrieve supplier risk scores."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError
from scvri_shared.kafka import get_producer
from scvri_shared.logging import get_logger
from scvri_shared.models.risk import SupplierRiskScore
from risk_intelligence.ml.feature_engineering import assemble_feature_vector
from risk_intelligence.ml.predictor import predict, score_to_level
from risk_intelligence.workers.risk_score_worker import compute_risk_score_task
from risk_intelligence.schemas.risk_score import (
    BulkRiskScoreRequest,
    SupplierRiskScoreResponse,
    TenantRiskSummaryResponse,
)

log = get_logger(__name__)

# Risk scores are fresh for 24 hours by default
_SCORE_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Champion model resolution
# ---------------------------------------------------------------------------
async def _get_champion_model(db: AsyncSession) -> dict:
    """Return the active champion model row from risk.model_registry.

    Falls back to a built-in rule-based model if none is registered.
    """
    result = await db.execute(text("""
        SELECT id, name, version, framework, artifact_path
        FROM risk.model_registry
        WHERE is_champion = TRUE
          AND status = 'champion'
        ORDER BY promoted_at DESC
        LIMIT 1
    """))
    row = result.mappings().one_or_none()
    if row:
        return dict(row)
    # Fallback to rule-based model (no artifact needed)
    return {
        "id": "rule-based-v1",
        "name": "rule_based",
        "version": "1.0",
        "framework": "rule_based",
        "artifact_path": "rule_based",
    }


# ---------------------------------------------------------------------------
# Compute single supplier risk score
# ---------------------------------------------------------------------------
async def compute_risk_score(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    force_recompute: bool = False,
    model_override: dict | None = None,
) -> SupplierRiskScore:
    """Compute and persist a risk score for one supplier.

    If a fresh score exists (within TTL) and force_recompute is False,
    the cached score is returned.
    """
    # Check freshness
    if not force_recompute:
        fresh = await _get_cached_score(db, supplier_id)
        if fresh:
            return fresh

    model = model_override or await _get_champion_model(db)

    # Assemble features and run inference
    fv = await assemble_feature_vector(db, tenant_id, supplier_id)
    result = predict(
        fv=fv,
        artifact_path=model["artifact_path"],
        framework=model["framework"],
        model_id=str(model["id"]),
        model_version=model["version"],
    )

    # Fetch previous score for delta
    prev_score = await _get_latest_score_value(db, supplier_id)

    # Persist in risk.supplier_risk_scores
    score_row = SupplierRiskScore(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        overall_score=result.risk_score,
        risk_level=result.risk_level,
        previous_score=prev_score,
        score_delta=round(result.risk_score - prev_score, 2) if prev_score is not None else None,
        model_id=str(model["id"]),
        model_version=model["version"],
        components=[c.model_dump() for c in result.components],
        computed_at=datetime.now(tz=timezone.utc),
        valid_until=datetime.now(tz=timezone.utc) + timedelta(hours=_SCORE_TTL_HOURS),
    )
    db.add(score_row)
    await db.flush()

    # Publish Kafka event
    async with get_producer() as producer:
        await producer.publish(
            topic="risk.events",
            key=str(supplier_id),
            value={
                "supplier_id": str(supplier_id),
                "tenant_id": str(tenant_id),
                "overall_score": result.risk_score,
                "risk_level": result.risk_level,
                "previous_score": prev_score,
                "score_delta": score_row.score_delta,
                "model_id": str(model["id"]),
            },
            event_type="risk.score.updated",
        )

    log.info(
        "risk_score.computed",
        supplier_id=str(supplier_id),
        score=result.risk_score,
        level=result.risk_level,
        latency_ms=result.latency_ms,
    )
    return score_row


async def _get_cached_score(
    db: AsyncSession, supplier_id: uuid.UUID
) -> SupplierRiskScore | None:
    result = await db.execute(
        select(SupplierRiskScore)
        .where(
            SupplierRiskScore.supplier_id == supplier_id,
            SupplierRiskScore.valid_until > datetime.now(tz=timezone.utc),
        )
        .order_by(desc(SupplierRiskScore.computed_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_latest_score_value(
    db: AsyncSession, supplier_id: uuid.UUID
) -> float | None:
    result = await db.execute(
        select(SupplierRiskScore.overall_score)
        .where(SupplierRiskScore.supplier_id == supplier_id)
        .order_by(desc(SupplierRiskScore.computed_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Get existing risk score
# ---------------------------------------------------------------------------
async def get_risk_score(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> SupplierRiskScore:
    result = await db.execute(
        select(SupplierRiskScore)
        .where(SupplierRiskScore.supplier_id == supplier_id)
        .order_by(desc(SupplierRiskScore.computed_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundError("risk_score", str(supplier_id))
    return row


# ---------------------------------------------------------------------------
# Score history
# ---------------------------------------------------------------------------
async def get_score_history(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    limit: int = 30,
) -> list[SupplierRiskScore]:
    result = await db.execute(
        select(SupplierRiskScore)
        .where(SupplierRiskScore.supplier_id == supplier_id)
        .order_by(desc(SupplierRiskScore.computed_at))
        .limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Bulk scoring
# ---------------------------------------------------------------------------
async def bulk_compute_risk_scores(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_ids: list[uuid.UUID],
    force_recompute: bool = False,
) -> dict[str, str]:
    """Enqueue Celery tasks for bulk computation (non-blocking).

    Returns a mapping of supplier_id → task_id.
    """
    task_map: dict[str, str] = {}
    for sid in supplier_ids:
        task = compute_risk_score_task.delay(
            str(sid), str(tenant_id), force_recompute
        )
        task_map[str(sid)] = task.id

    return task_map


# ---------------------------------------------------------------------------
# Tenant-level risk summary
# ---------------------------------------------------------------------------
async def get_tenant_risk_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantRiskSummaryResponse:
    """Aggregate risk distribution across all suppliers for a tenant."""
    result = await db.execute(text("""
        WITH latest_scores AS (
            SELECT DISTINCT ON (supplier_id)
                   supplier_id, overall_score, risk_level
            FROM risk.supplier_risk_scores
            ORDER BY supplier_id, computed_at DESC
        ),
        supplier_count AS (
            SELECT COUNT(*) AS total
            FROM supplier.suppliers
            WHERE deleted_at IS NULL AND status != 'inactive'
        )
        SELECT
            (SELECT total FROM supplier_count)                              AS total_suppliers,
            COUNT(*) FILTER (WHERE risk_level = 'critical')                AS critical_count,
            COUNT(*) FILTER (WHERE risk_level = 'high')                    AS high_count,
            COUNT(*) FILTER (WHERE risk_level = 'medium')                  AS medium_count,
            COUNT(*) FILTER (WHERE risk_level = 'low')                     AS low_count,
            COUNT(*) FILTER (WHERE risk_level = 'minimal')                 AS minimal_count,
            ROUND(AVG(overall_score)::NUMERIC, 2)                          AS avg_risk_score
        FROM latest_scores
    """))
    row = result.mappings().one()

    total = int(row["total_suppliers"] or 0)
    scored = (
        int(row["critical_count"] or 0)
        + int(row["high_count"] or 0)
        + int(row["medium_count"] or 0)
        + int(row["low_count"] or 0)
        + int(row["minimal_count"] or 0)
    )

    return TenantRiskSummaryResponse(
        tenant_id=tenant_id,
        total_suppliers=total,
        critical_count=int(row["critical_count"] or 0),
        high_count=int(row["high_count"] or 0),
        medium_count=int(row["medium_count"] or 0),
        low_count=int(row["low_count"] or 0),
        minimal_count=int(row["minimal_count"] or 0),
        unscored_count=max(0, total - scored),
        avg_risk_score=float(row["avg_risk_score"] or 0.0),
        computed_at=datetime.now(tz=timezone.utc),
    )
