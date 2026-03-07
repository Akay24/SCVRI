"""Feature engineering pipeline.

Assembles a FeatureVector from raw database records so that it can be
fed to the ML model or the rule-based fallback scorer.

Data sources queried per supplier:
  - supplier.suppliers                       (tier, onboarding, country, certifications)
  - supplier.supplier_scorecards (latest)    (OTD, fill, defect, invoice)
  - risk.kri_snapshots                       (KRI composite + red/amber counts)
  - supply_chain.purchase_orders             (spend concentration)
  - compliance.certificates                  (active / expired counts)
  - static country risk table (in-memory)

All queries are executed against the caller-supplied AsyncSession which
already has RLS SET so tenant isolation is guaranteed.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.logging import get_logger
from risk_intelligence.schemas.model import FeatureVector

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Static country risk scores — World Bank / OECD country risk classification
# (0 = very low, 100 = very high)
# Production: loaded from S3 reference table; this is a concise seed.
# ---------------------------------------------------------------------------
_COUNTRY_RISK: dict[str, float] = {
    "US": 5.0,  "GB": 6.0,  "DE": 5.0,  "FR": 8.0,  "JP": 5.0,
    "SG": 5.0,  "AU": 5.0,  "CA": 5.0,  "NL": 5.0,  "CH": 4.0,
    "CN": 35.0, "IN": 40.0, "RU": 80.0, "BR": 45.0, "MX": 42.0,
    "NG": 70.0, "PK": 72.0, "BD": 65.0, "VN": 38.0, "ID": 42.0,
    "TH": 36.0, "PH": 45.0, "TR": 55.0, "ZA": 50.0, "EG": 58.0,
    "IR": 90.0, "KP": 95.0, "BY": 85.0, "MM": 75.0, "UA": 68.0,
}
_DEFAULT_COUNTRY_RISK = 50.0

_TIER_ENCODING: dict[str, float] = {
    "tier_1": 1.0,
    "tier_2": 0.75,
    "tier_3": 0.5,
    "tier_4": 0.25,
}
_ONBOARDING_ENCODING: dict[str, float] = {
    "active": 1.0,
    "approved": 0.9,
    "under_review": 0.6,
    "submitted": 0.5,
    "draft": 0.4,
    "returned": 0.35,
    "suspended": 0.2,
    "rejected": 0.1,
    "inactive": 0.0,
}


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------
async def assemble_feature_vector(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> FeatureVector:
    """Build a complete FeatureVector for a supplier.

    Queries are run in parallel where possible via separate awaits;
    everything lands in the same SAVEPOINT within one connection.
    """
    supplier_row, scorecard_row, kri_row, cert_row, spend_row = await _fetch_all(
        db, tenant_id, supplier_id
    )

    # ---- Supplier base ----
    if supplier_row is None:
        log.warning("feature_engineering.supplier_not_found", supplier_id=str(supplier_id))
        return _default_vector(supplier_id, tenant_id)

    country_code = supplier_row.get("country_code", "XX")
    country_risk = _COUNTRY_RISK.get(country_code, _DEFAULT_COUNTRY_RISK)

    tier = supplier_row.get("supplier_tier", "tier_3")
    tier_enc = _TIER_ENCODING.get(tier, 0.5)

    onboarding = supplier_row.get("onboarding_status", "draft")
    onboarding_enc = _ONBOARDING_ENCODING.get(onboarding, 0.5)

    employee_count = supplier_row.get("employee_count") or 1
    employee_count_log = math.log10(max(employee_count, 1))

    created_at: date | None = supplier_row.get("created_at")
    if created_at:
        years = (datetime.now(tz=timezone.utc).date() - created_at).days / 365.0
    else:
        years = 5.0

    # ---- Scorecard ----
    otd_rate = 50.0
    fill_rate = 50.0
    defect_rate = 0.0
    invoice_accuracy = 100.0
    overall_scorecard = 50.0
    scorecard_age_days = 999

    if scorecard_row:
        otd_rate = float(scorecard_row.get("otd_rate") or 50.0)
        fill_rate = float(scorecard_row.get("fill_rate") or 50.0)
        defect_rate = float(scorecard_row.get("defect_rate") or 0.0)
        invoice_accuracy = float(scorecard_row.get("invoice_accuracy_rate") or 100.0)
        overall_scorecard = float(scorecard_row.get("overall_score") or 50.0)
        if scorecard_row.get("period_end"):
            scorecard_age_days = (datetime.now(tz=timezone.utc).date() - scorecard_row["period_end"]).days

    # ---- KRI ----
    composite_kri = float(kri_row.get("composite", 50.0)) if kri_row else 50.0
    kri_red = int(kri_row.get("red_count", 0)) if kri_row else 0
    kri_amber = int(kri_row.get("amber_count", 0)) if kri_row else 0

    # ---- Certifications ----
    active_certs = int(cert_row.get("active_count", 0)) if cert_row else 0
    expired_certs = int(cert_row.get("expired_count", 0)) if cert_row else 0

    # ---- Spend concentration ----
    spend_pct = float(spend_row.get("concentration_pct", 0.0)) if spend_row else 0.0
    is_sole_source = active_certs == 0 and spend_pct > 80.0

    return FeatureVector(
        supplier_id=supplier_id,
        tenant_id=tenant_id,
        otd_rate=otd_rate,
        fill_rate=fill_rate,
        defect_rate=defect_rate,
        invoice_accuracy_rate=invoice_accuracy,
        overall_scorecard_score=overall_scorecard,
        scorecard_age_days=scorecard_age_days,
        composite_kri_score=composite_kri,
        kri_red_count=kri_red,
        kri_amber_count=kri_amber,
        supplier_tier_encoded=tier_enc,
        onboarding_status_encoded=onboarding_enc,
        years_in_business=years,
        employee_count_log=employee_count_log,
        country_risk_score=country_risk,
        active_certifications_count=active_certs,
        expired_certifications_count=expired_certs,
        compliance_violations_count=0,
        is_sole_source=is_sole_source,
        spend_concentration_pct=spend_pct,
    )


# ---------------------------------------------------------------------------
# Parallel DB fetches
# ---------------------------------------------------------------------------
async def _fetch_all(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> tuple[Any, Any, Any, Any, Any]:
    """Fetch all feature source rows in one round-trip (fire-and-forget style)."""

    # Supplier base
    supplier = await db.execute(text("""
        SELECT id, country_code, supplier_tier, onboarding_status,
               employee_count, DATE(created_at) AS created_at
        FROM supplier.suppliers
        WHERE id = :sid
          AND deleted_at IS NULL
        LIMIT 1
    """), {"sid": str(supplier_id)})
    supplier_row = supplier.mappings().one_or_none()

    # Latest scorecard
    scorecard = await db.execute(text("""
        SELECT otd_rate, fill_rate, defect_rate, invoice_accuracy_rate,
               overall_score, period_end
        FROM supplier.supplier_scorecards
        WHERE supplier_id = :sid
        ORDER BY period_end DESC
        LIMIT 1
    """), {"sid": str(supplier_id)})
    scorecard_row = scorecard.mappings().one_or_none()

    # KRI aggregate (last 30 days)
    kri = await db.execute(text("""
        SELECT
            AVG(CASE WHEN status = 'red'   THEN 100
                     WHEN status = 'amber' THEN 60
                     ELSE 20 END)          AS composite,
            COUNT(*) FILTER (WHERE status = 'red')   AS red_count,
            COUNT(*) FILTER (WHERE status = 'amber') AS amber_count
        FROM risk.kri_snapshots
        WHERE supplier_id = :sid
          AND measured_at >= NOW() - INTERVAL '30 days'
    """), {"sid": str(supplier_id)})
    kri_row = kri.mappings().one_or_none()

    # Certifications
    certs = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'active')  AS active_count,
            COUNT(*) FILTER (WHERE status = 'expired') AS expired_count
        FROM supplier.certifications
        WHERE supplier_id = :sid
    """), {"sid": str(supplier_id)})
    cert_row = certs.mappings().one_or_none()

    # Spend concentration
    spend = await db.execute(text("""
        SELECT
            ROUND(
                100.0 * SUM(po.total_amount_usd)
                / NULLIF(
                    (SELECT SUM(total_amount_usd) FROM supply_chain.purchase_orders
                     WHERE tenant_id = :tid::uuid
                       AND order_date >= NOW() - INTERVAL '365 days'),
                    0
                ), 2
            ) AS concentration_pct
        FROM supply_chain.purchase_orders po
        WHERE po.supplier_id = :sid
          AND po.order_date >= NOW() - INTERVAL '365 days'
    """), {"sid": str(supplier_id), "tid": str(tenant_id)})
    spend_row = spend.mappings().one_or_none()

    return supplier_row, scorecard_row, kri_row, cert_row, spend_row


def _default_vector(supplier_id: uuid.UUID, tenant_id: uuid.UUID) -> FeatureVector:
    """Return a neutral feature vector when data is unavailable."""
    return FeatureVector(supplier_id=supplier_id, tenant_id=tenant_id)
