"""KRI evaluation Celery worker.

Runs every 6 hours (Beat schedule).

For each tenant:
  1. Fetch all suppliers with active KRI definitions
  2. Pull latest raw data from available data sources (scorecard API, financial feeds)
  3. Record KRI snapshots via kri_service.record_kri_snapshot
  4. The service emits Kafka events for threshold breaches automatically

Currently supported automatic data sources:
  - 'scorecard'  — reads from supplier.supplier_scorecards
  - 'manual'     — skipped (requires explicit API call)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from scvri_shared.config import settings
from scvri_shared.logging import get_logger
from risk_intelligence.workers.celery_app import app

log = get_logger(__name__)


@app.task(
    name="risk_intelligence.workers.kri_evaluation_worker.evaluate_all_kris_task",
    max_retries=2,
    default_retry_delay=300,
)
def evaluate_all_kris_task() -> dict:
    """Evaluate all auto-computable KRIs for all active suppliers/tenants."""
    log.info("kri_evaluation.start")
    stats = asyncio.run(_async_evaluate_kris())
    log.info("kri_evaluation.done", **stats)
    return stats


async def _async_evaluate_kris() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    from risk_intelligence.services import kri_service  # noqa: PLC0415
    from risk_intelligence.schemas.kri import KRISnapshotCreate  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    snapshots_created = 0
    breaches = 0

    async with async_session() as db:
        # All auto-computable KRI definitions grouped by tenant
        kri_rows = (await db.execute(text("""
            SELECT kd.id          AS kri_id,
                   kd.tenant_id,
                   kd.name,
                   kd.data_source,
                   kd.category,
                   kd.green_threshold,
                   kd.amber_threshold,
                   kd.is_inverted
            FROM risk.kri_definitions kd
            WHERE kd.data_source = 'scorecard'
               OR kd.is_global = TRUE
        """))).mappings().all()

        for kri in kri_rows:
            tenant_id = kri["tenant_id"]
            if tenant_id is None:
                continue  # global definitions without tenant scope — skip automatic eval

            await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})

            # Get all active suppliers for this tenant
            suppliers = (await db.execute(text("""
                SELECT id FROM supplier.suppliers
                WHERE status = 'active' AND deleted_at IS NULL
            """))).scalars().all()

            for supplier_id in suppliers:
                value = await _fetch_kri_value(db, kri, supplier_id)
                if value is None:
                    continue

                snap_data = KRISnapshotCreate(
                    supplier_id=supplier_id,
                    kri_definition_id=kri["kri_id"],
                    value=value,
                )
                try:
                    snap = await kri_service.record_kri_snapshot(
                        db, tenant_id, uuid.UUID("00000000-0000-0000-0000-000000000000"),
                        snap_data
                    )
                    snapshots_created += 1
                    if snap.status in {"amber", "red"}:
                        breaches += 1
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "kri_eval.snapshot_failed",
                        supplier_id=str(supplier_id),
                        kri_id=str(kri["kri_id"]),
                        error=str(exc),
                    )

        await db.commit()

    await engine.dispose()
    return {"snapshots_created": snapshots_created, "breaches_detected": breaches}


async def _fetch_kri_value(db, kri: dict, supplier_id: uuid.UUID) -> float | None:
    """Compute the current KRI value from its data source."""
    from sqlalchemy import text  # noqa: PLC0415

    data_source = kri.get("data_source", "manual")
    category = kri.get("category", "operational")

    if data_source == "scorecard":
        return await _scorecard_kri_value(db, kri, supplier_id)

    return None


async def _scorecard_kri_value(db, kri: dict, supplier_id: uuid.UUID) -> float | None:
    """Map scorecard fields to KRI values based on KRI name convention."""
    from sqlalchemy import text  # noqa: PLC0415

    name = kri["name"].lower()
    col_map = {
        "otd_rate": "otd_rate",
        "on_time_delivery": "otd_rate",
        "fill_rate": "fill_rate",
        "defect_rate": "defect_rate",
        "invoice_accuracy": "invoice_accuracy_rate",
        "overall_score": "overall_score",
    }

    # Find matching column
    col = None
    for key, db_col in col_map.items():
        if key in name:
            col = db_col
            break

    if col is None:
        return None

    result = await db.execute(text(f"""
        SELECT {col}
        FROM supplier.supplier_scorecards
        WHERE supplier_id = :sid
        ORDER BY period_end DESC
        LIMIT 1
    """), {"sid": str(supplier_id)})
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None
