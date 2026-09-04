"""Risk score Celery worker.

Tasks:
  - compute_risk_score_task: compute and persist a single supplier risk score
  - rescore_all_suppliers_task: nightly batch for all active suppliers in all tenants
"""
from __future__ import annotations

import asyncio
import uuid

from celery import Task

from scvri_shared.config import settings
from scvri_shared.logging import get_logger
from risk_intelligence.workers.celery_app import app

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Single-supplier scoring task
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="risk_intelligence.workers.risk_score_worker.compute_risk_score_task",
    max_retries=3,
    default_retry_delay=120,
)
def compute_risk_score_task(
    self: Task,
    supplier_id: str,
    tenant_id: str,
    force_recompute: bool = False,
) -> dict:
    """Compute risk score for a single supplier.

    Uses a synchronous SQLAlchemy session inside asyncio.run to keep Celery
    happy (Celery workers are sync by default).
    """
    log.info("risk_score_task.start", supplier_id=supplier_id, tenant_id=tenant_id)

    try:
        result = asyncio.run(
            _async_compute(
                uuid.UUID(supplier_id),
                uuid.UUID(tenant_id),
                force_recompute=force_recompute,
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.error("risk_score_task.failed", supplier_id=supplier_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}

    log.info(
        "risk_score_task.done",
        supplier_id=supplier_id,
        score=result.get("score"),
        level=result.get("level"),
    )
    return result


async def _async_compute(
    supplier_id: uuid.UUID,
    tenant_id: uuid.UUID,
    force_recompute: bool,
) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from risk_intelligence.services import risk_scoring_service  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        async with db.begin():
            await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})
            row = await risk_scoring_service.compute_risk_score(
                db, tenant_id, supplier_id, force_recompute=force_recompute
            )

    await engine.dispose()
    return {"status": "ok", "score": row.overall_score, "level": row.risk_level}


# ---------------------------------------------------------------------------
# Nightly batch task
# ---------------------------------------------------------------------------
@app.task(
    name="risk_intelligence.workers.risk_score_worker.rescore_all_suppliers_task",
    max_retries=1,
    default_retry_delay=300,
)
def rescore_all_suppliers_task() -> dict:
    """Recompute risk scores for all active suppliers across all tenants."""
    log.info("risk_rescore.batch.start")
    count = asyncio.run(_async_batch_rescore())
    log.info("risk_rescore.batch.done", total=count)
    return {"total_scored": count}


async def _async_batch_rescore() -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from risk_intelligence.services import risk_scoring_service  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    total = 0

    async with async_session() as db:
        # Get all (tenant_id, supplier_id) pairs for active suppliers
        rows = (await db.execute(text("""
            SELECT t.id AS tenant_id, s.id AS supplier_id
            FROM platform.tenants t
            JOIN supplier.suppliers s ON s.tenant_id = t.id
            WHERE t.status = 'active'
              AND s.status = 'active'
              AND s.deleted_at IS NULL
            ORDER BY t.id, s.created_at
        """))).mappings().all()

    await engine.dispose()

    for row in rows:
        compute_risk_score_task.delay(
            str(row["supplier_id"]),
            str(row["tenant_id"]),
            False,
        )
        total += 1

    return total
