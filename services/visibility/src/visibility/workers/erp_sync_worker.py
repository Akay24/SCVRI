"""ERP sync and shipment reconciliation Celery tasks.

``erp_sync_pos_task``        — every 30 min: pull PO delta from ERP HTTP API
``reconcile_shipments_task`` — daily 03:00 UTC: reconcile in-transit shipment
                               statuses against carrier tracking APIs
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from scvri_shared.config import settings
from scvri_shared.logging import get_logger
from visibility.workers.celery_app import app

log = get_logger(__name__)


# ── ERP PO Sync ───────────────────────────────────────────────────────────────

@app.task(
    name="visibility.workers.erp_sync_worker.erp_sync_pos_task",
    max_retries=3,
    default_retry_delay=60,
)
def erp_sync_pos_task() -> dict:
    """Pull PO delta from external ERP API and upsert into visibility DB."""
    log.info("erp_sync.pos.start")
    result = asyncio.run(_async_erp_sync_pos())
    log.info("erp_sync.pos.done", **result)
    return result


async def _async_erp_sync_pos() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    import httpx  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Fetch modified_since from last sync marker (or last 35 minutes to overlap)
    modified_since = datetime.now(timezone.utc) - timedelta(minutes=35)

    created = updated = errors = 0

    # Only attempt ERP sync if the integration URL is configured
    erp_url = getattr(settings, "erp_api_url", None)
    if not erp_url:
        log.info("erp_sync.skipped.no_url")
        await engine.dispose()
        return {"created": 0, "updated": 0, "errors": 0, "skipped": True}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{erp_url}/api/purchase-orders",
                params={"modified_since": modified_since.isoformat()},
                headers={"Authorization": f"Bearer {getattr(settings, 'erp_api_key', '')}"},
            )
            resp.raise_for_status()
            po_list: list[dict] = resp.json().get("data", [])

    except Exception as exc:  # noqa: BLE001
        log.warning("erp_sync.fetch_failed", error=str(exc))
        await engine.dispose()
        return {"created": 0, "updated": 0, "errors": 1}

    from visibility.services import po_service  # noqa: PLC0415
    from visibility.schemas.purchase_order import PurchaseOrderCreate, POEventRequest  # noqa: PLC0415

    for po_data in po_list:
        try:
            tenant_id = uuid.UUID(po_data["tenant_id"])
            system_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

            async with async_session() as db:
                await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})

                exists = (await db.execute(text("""
                    SELECT id, status FROM visibility.purchase_orders
                    WHERE tenant_id = :t AND po_number = :po_num
                """), {"t": str(tenant_id), "po_num": po_data["po_number"]})).mappings().one_or_none()

                if exists is None:
                    po_in = PurchaseOrderCreate(**po_data)
                    await po_service.create_purchase_order(db, tenant_id, system_user_id, po_in)
                    created += 1
                else:
                    # Apply status change if ERP says it's confirmed and we're still draft
                    erp_status = po_data.get("status", "draft")
                    current_status = exists["status"]
                    if erp_status == "confirmed" and current_status == "draft":
                        await po_service.apply_po_event(
                            db, tenant_id, system_user_id,
                            uuid.UUID(str(exists["id"])),
                            POEventRequest(event="confirm", notes="ERP sync"),
                        )
                        updated += 1

        except Exception as exc:  # noqa: BLE001
            log.warning("erp_sync.po_error", po_number=po_data.get("po_number"), error=str(exc))
            errors += 1

    await engine.dispose()
    return {"created": created, "updated": updated, "errors": errors}


# ── Shipment Reconciliation ──────────────────────────────────────────────────

@app.task(
    name="visibility.workers.erp_sync_worker.reconcile_shipments_task",
    max_retries=2,
    default_retry_delay=300,
)
def reconcile_shipments_task() -> dict:
    """Reconcile in-transit shipment statuses against carrier tracking APIs."""
    log.info("reconcile_shipments.start")
    result = asyncio.run(_async_reconcile_shipments())
    log.info("reconcile_shipments.done", **result)
    return result


async def _async_reconcile_shipments() -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415
    import httpx  # noqa: PLC0415

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    reconciled = not_found = errors = 0

    async with async_session() as db:
        # All in-transit shipments across all tenants
        rows = (await db.execute(text("""
            SELECT id, tenant_id, tracking_number, carrier, carrier_type, estimated_arrival
            FROM visibility.shipments
            WHERE status IN ('picked_up', 'in_transit', 'out_for_delivery', 'customs_hold')
              AND updated_at < now() - interval '4 hours'
            ORDER BY updated_at ASC
            LIMIT 200
        """))).mappings().all()

    from visibility.services.shipment_service import add_tracking_event  # noqa: PLC0415
    from visibility.schemas.shipment import TrackingEventCreate  # noqa: PLC0415

    carrier_api_url = getattr(settings, "carrier_tracking_api_url", None)

    for shipment in rows:
        if not carrier_api_url:
            # No carrier API configured — skip reconciliation
            break

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{carrier_api_url}/track",
                    params={
                        "tracking_number": shipment["tracking_number"],
                        "carrier": shipment["carrier"],
                    },
                    headers={"Authorization": f"Bearer {getattr(settings, 'carrier_api_key', '')}"},
                )

            if resp.status_code == 404:
                not_found += 1
                continue

            resp.raise_for_status()
            data = resp.json()

            latest_event = data.get("latest_event")
            if not latest_event:
                continue

            tenant_id = uuid.UUID(str(shipment["tenant_id"]))
            shipment_id = uuid.UUID(str(shipment["id"]))

            async with async_session() as db:
                await db.execute(text("SET LOCAL scvri.tenant_id = :tid"), {"tid": str(tenant_id)})

                event_in = TrackingEventCreate(
                    shipment_id=shipment_id,
                    event_type=latest_event["type"],
                    location=latest_event.get("location", "Unknown"),
                    description=latest_event.get("description"),
                    occurred_at=datetime.fromisoformat(latest_event["timestamp"]),
                    carrier_reference=latest_event.get("carrier_reference"),
                )
                await add_tracking_event(db, tenant_id, event_in)
                reconciled += 1

        except Exception as exc:  # noqa: BLE001
            log.warning(
                "reconcile.shipment_error",
                shipment_id=str(shipment["id"]),
                error=str(exc),
            )
            errors += 1

    await engine.dispose()
    return {"reconciled": reconciled, "not_found": not_found, "errors": errors}
