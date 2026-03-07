"""Celery tasks for scorecard computation and document virus scanning.

Tasks:
  - compute_supplier_scorecard: recompute a single supplier's scorecard for a period
  - scan_document_task: shell out to ClamAV to scan an S3 document
"""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import uuid
from datetime import date

import boto3
from celery import shared_task
from sqlalchemy import select, update

from scvri_shared.config import settings
from scvri_shared.logging import get_logger
from scvri_shared.models.supplier import SupplierDocument
from supplier_management.workers.celery_app import app

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_sync_db_session(tenant_id_str: str):
    """Return a synchronous SQLAlchemy session with RLS set."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    engine = create_engine(str(settings.database_url_sync), pool_pre_ping=True)
    sess = Session(engine)
    sess.execute(text(f"SET LOCAL scvri.tenant_id = '{tenant_id_str}'"))
    return sess


# ---------------------------------------------------------------------------
# Scorecard computation task
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="supplier_management.workers.scorecard_worker.compute_supplier_scorecard",
    max_retries=3,
    default_retry_delay=120,
)
def compute_supplier_scorecard(
    self,
    supplier_id: str,
    tenant_id: str,
    period_start: str,
    period_end: str,
) -> dict:
    """Compute and persist a scorecard for a supplier over a given period.

    Fetches PO / shipment aggregates from the supply_chain schema and
    calls scorecard_service.create_scorecard synchronously via asyncio.run.
    """
    from sqlalchemy import create_engine, text  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    log.info(
        "scorecard.compute.start",
        supplier_id=supplier_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )

    engine = create_engine(str(settings.database_url_sync), pool_pre_ping=True)

    with Session(engine) as sess:
        sess.execute(text(f"SET LOCAL scvri.tenant_id = '{tenant_id}'"))

        # Aggregate delivery metrics from purchase orders + shipments
        row = sess.execute(text("""
            SELECT
                COUNT(*)                                        AS total_deliveries,
                SUM(CASE WHEN s.actual_delivery_date <= po.required_delivery_date
                         THEN 1 ELSE 0 END)                    AS on_time_deliveries,
                COALESCE(SUM(pol.quantity_ordered), 0)         AS quantity_ordered,
                COALESCE(SUM(pol.quantity_received), 0)        AS quantity_received
            FROM supply_chain.purchase_orders po
            JOIN supply_chain.shipments s ON s.purchase_order_id = po.id
            JOIN supply_chain.purchase_order_lines pol ON pol.purchase_order_id = po.id
            WHERE po.supplier_id = :supplier_id
              AND po.tenant_id = :tenant_id::uuid
              AND po.order_date BETWEEN :period_start AND :period_end
        """), {
            "supplier_id": supplier_id,
            "tenant_id": tenant_id,
            "period_start": period_start,
            "period_end": period_end,
        }).mappings().one_or_none()

        if row is None or row["total_deliveries"] == 0:
            log.info("scorecard.compute.no_data", supplier_id=supplier_id)
            return {"status": "no_data"}

        from supplier_management.schemas.scorecard import ScorecardCreate  # noqa: PLC0415

        data = ScorecardCreate(
            period_start=date.fromisoformat(period_start),
            period_end=date.fromisoformat(period_end),
            total_deliveries=int(row["total_deliveries"]),
            on_time_deliveries=int(row["on_time_deliveries"]),
            quantity_ordered=int(row["quantity_ordered"]),
            quantity_received=int(row["quantity_received"]),
            quantity_returned=0,
        )

        from supplier_management.services.scorecard_service import (  # noqa: PLC0415
            _compute_grade,
            _compute_overall,
            _safe_rate,
        )
        from scvri_shared.models.supplier import SupplierScorecard  # noqa: PLC0415

        otd = _safe_rate(data.on_time_deliveries, data.total_deliveries)
        fill = _safe_rate(data.quantity_received, data.quantity_ordered)
        defect = _safe_rate(data.quantity_returned, data.quantity_received)
        overall = _compute_overall(otd, fill, defect, 100.0)
        grade = _compute_grade(overall)

        sc = SupplierScorecard(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            supplier_id=uuid.UUID(supplier_id),
            period_start=data.period_start,
            period_end=data.period_end,
            total_deliveries=data.total_deliveries,
            on_time_deliveries=data.on_time_deliveries,
            otd_rate=otd,
            quantity_ordered=data.quantity_ordered,
            quantity_received=data.quantity_received,
            quantity_returned=0,
            fill_rate=fill,
            defect_rate=defect,
            invoice_accuracy_rate=100.0,
            overall_score=overall,
            grade=grade,
        )
        sess.add(sc)
        sess.commit()

    log.info("scorecard.compute.done", supplier_id=supplier_id, grade=grade, score=overall)
    return {"status": "ok", "grade": grade, "score": overall}


# ---------------------------------------------------------------------------
# Document virus scan task
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="supplier_management.workers.scorecard_worker.scan_document_task",
    max_retries=2,
    default_retry_delay=30,
)
def scan_document_task(self, document_id: str, tenant_id: str) -> dict:
    """Download document from S3, run ClamAV clamscan, update upload_status."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    log.info("document.scan.start", doc_id=document_id, tenant_id=tenant_id)

    engine = create_engine(str(settings.database_url_sync), pool_pre_ping=True)

    with Session(engine) as sess:
        sess.execute(text(f"SET LOCAL scvri.tenant_id = '{tenant_id}'"))

        doc = sess.execute(
            select(SupplierDocument).where(SupplierDocument.id == uuid.UUID(document_id))
        ).scalar_one_or_none()

        if doc is None:
            log.warning("document.scan.not_found", doc_id=document_id)
            return {"status": "not_found"}

        try:
            s3 = boto3.client(
                "s3",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )

            with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
                s3.download_fileobj(doc.s3_bucket, doc.s3_key, tmp)
                tmp_path = tmp.name

            # Run ClamAV
            result = subprocess.run(
                ["clamscan", "--no-summary", tmp_path],
                capture_output=True,
                text=True,
                timeout=120,
            )

            import os  # noqa: PLC0415
            os.unlink(tmp_path)

            # clamscan exit code: 0 = clean, 1 = infected, 2 = error
            if result.returncode == 0:
                new_status = "clean"
            elif result.returncode == 1:
                new_status = "infected"
                log.warning("document.scan.infected", doc_id=document_id)
            else:
                new_status = "failed"
                log.error("document.scan.error", doc_id=document_id, stderr=result.stderr)

        except Exception as exc:  # noqa: BLE001
            log.error("document.scan.exception", doc_id=document_id, error=str(exc))
            new_status = "failed"

        sess.execute(
            update(SupplierDocument)
            .where(SupplierDocument.id == uuid.UUID(document_id))
            .values(upload_status=new_status)
        )
        sess.commit()

    log.info("document.scan.done", doc_id=document_id, result=new_status)
    return {"status": new_status}
