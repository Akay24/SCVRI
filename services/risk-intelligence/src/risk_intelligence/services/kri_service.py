"""KRI (Key Risk Indicator) service — definition management, snapshot recording,
threshold evaluation, and dashboard aggregation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError
from scvri_shared.kafka import get_producer
from scvri_shared.logging import get_logger
from scvri_shared.models.risk import KRIDefinition, KRISnapshot
from risk_intelligence.schemas.kri import (
    KRIDefinitionCreate,
    KRISnapshotCreate,
    KRISnapshotResponse,
    KRIStatus,
    SupplierKRIDashboard,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Threshold evaluation helpers
# ---------------------------------------------------------------------------
def _evaluate_threshold(value: float, kri: KRIDefinition) -> KRIStatus:
    """Determine RED / AMBER / GREEN status for a KRI value.

    is_inverted = True means LOWER is BAD (e.g. cash ratio, headroom, days-to-pay).
    """
    if kri.is_inverted:
        if value <= kri.amber_threshold:
            return "red"
        if value <= kri.green_threshold:
            return "amber"
        return "green"
    else:
        if value > kri.amber_threshold:
            return "red"
        if value > kri.green_threshold:
            return "amber"
        return "green"


# ---------------------------------------------------------------------------
# KRI Definitions
# ---------------------------------------------------------------------------
async def create_kri_definition(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: KRIDefinitionCreate,
) -> KRIDefinition:
    defn = KRIDefinition(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        category=data.category,
        unit=data.unit,
        aggregation_method=data.aggregation_method,
        green_threshold=data.green_threshold,
        amber_threshold=data.amber_threshold,
        weight=data.weight,
        is_inverted=data.is_inverted,
        is_global=data.is_global,
        data_source=data.data_source,
        created_by=user_id,
    )
    db.add(defn)
    await db.flush()
    return defn


async def list_kri_definitions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[KRIDefinition]:
    result = await db.execute(
        select(KRIDefinition).where(
            (KRIDefinition.tenant_id == tenant_id) | (KRIDefinition.is_global == True)  # noqa: E712
        ).order_by(KRIDefinition.category, KRIDefinition.name)
    )
    return list(result.scalars().all())


async def get_kri_definition(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    kri_id: uuid.UUID,
) -> KRIDefinition:
    result = await db.execute(
        select(KRIDefinition).where(KRIDefinition.id == kri_id)
    )
    defn = result.scalar_one_or_none()
    if defn is None:
        raise NotFoundError("kri_definition", str(kri_id))
    return defn


# ---------------------------------------------------------------------------
# KRI Snapshots
# ---------------------------------------------------------------------------
async def record_kri_snapshot(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: KRISnapshotCreate,
) -> KRISnapshot:
    """Record a KRI measurement and evaluate threshold status.

    Emits a `kri.threshold.breached` Kafka event if status worsened.
    """
    defn = await get_kri_definition(db, tenant_id, data.kri_definition_id)

    new_status = _evaluate_threshold(data.value, defn)

    # Get previous status for breach detection
    prev_result = await db.execute(
        select(KRISnapshot.status)
        .where(
            KRISnapshot.supplier_id == data.supplier_id,
            KRISnapshot.kri_definition_id == data.kri_definition_id,
        )
        .order_by(desc(KRISnapshot.measured_at))
        .limit(1)
    )
    prev_status: KRIStatus | None = prev_result.scalar_one_or_none()

    snapshot = KRISnapshot(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        supplier_id=data.supplier_id,
        kri_definition_id=data.kri_definition_id,
        value=data.value,
        status=new_status,
        raw_data=data.raw_data,
        measured_at=datetime.now(tz=timezone.utc),
        recorded_by=user_id,
    )
    db.add(snapshot)
    await db.flush()

    # Emit Kafka event if status worsened (green→amber, amber→red, green→red)
    _status_rank = {"green": 0, "amber": 1, "red": 2}
    if prev_status and _status_rank.get(new_status, 0) > _status_rank.get(prev_status, 0):
        async with get_producer() as producer:
            await producer.publish(
                topic="risk.events",
                key=str(data.supplier_id),
                value={
                    "tenant_id": str(tenant_id),
                    "supplier_id": str(data.supplier_id),
                    "kri_definition_id": str(data.kri_definition_id),
                    "kri_name": defn.name,
                    "category": defn.category,
                    "previous_status": prev_status,
                    "new_status": new_status,
                    "value": data.value,
                    "threshold": defn.amber_threshold if new_status == "amber" else defn.green_threshold,
                    "measured_at": snapshot.measured_at.isoformat(),
                },
                event_type="kri.threshold.breached",
            )
        log.warning(
            "kri.threshold.breached",
            supplier_id=str(data.supplier_id),
            kri=defn.name,
            from_status=prev_status,
            to_status=new_status,
            value=data.value,
        )

    return snapshot


async def get_supplier_kri_dashboard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> SupplierKRIDashboard:
    """Return the latest snapshot per KRI for a supplier."""
    result = await db.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (kri_definition_id)
                   ks.id, ks.supplier_id, ks.kri_definition_id,
                   ks.value, ks.status, ks.measured_at,
                   kd.name  AS kri_name,
                   kd.category,
                   kd.unit
            FROM risk.kri_snapshots ks
            JOIN risk.kri_definitions kd ON kd.id = ks.kri_definition_id
            WHERE ks.supplier_id = :supplier_id
            ORDER BY kri_definition_id, ks.measured_at DESC
        )
        SELECT *,
               SUM(CASE WHEN status = 'red'   THEN 100
                        WHEN status = 'amber' THEN 60
                        ELSE 20 END)::float / NULLIF(COUNT(*), 0) AS composite
        FROM latest
        GROUP BY id, supplier_id, kri_definition_id, value, status,
                 measured_at, kri_name, category, unit
    """), {"supplier_id": str(supplier_id)})

    rows = result.mappings().all()

    snapshots = [
        KRISnapshotResponse(
            id=r["id"],
            supplier_id=r["supplier_id"],
            kri_definition_id=r["kri_definition_id"],
            kri_name=r["kri_name"],
            category=r["category"],
            value=float(r["value"]),
            status=r["status"],
            unit=r["unit"],
            measured_at=r["measured_at"],
        )
        for r in rows
    ]

    red = sum(1 for s in snapshots if s.status == "red")
    amber = sum(1 for s in snapshots if s.status == "amber")
    green = len(snapshots) - red - amber
    composite = float(rows[0]["composite"]) if rows else 50.0

    last_eval = max((s.measured_at for s in snapshots), default=None)

    return SupplierKRIDashboard(
        supplier_id=supplier_id,
        snapshots=snapshots,
        red_count=red,
        amber_count=amber,
        green_count=green,
        composite_kri_score=round(composite, 2),
        last_evaluated_at=last_eval,
    )
