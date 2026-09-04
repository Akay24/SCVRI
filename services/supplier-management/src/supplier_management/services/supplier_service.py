"""Core supplier business logic.

Responsibilities:
- CRUD for Supplier + Contact + Certification records (all scoped to tenant_id via RLS)
- Full-text search with multi-filter composition
- Onboarding state-machine transitions with Kafka event emission
- Soft delete (sets status=inactive + deleted_at)
- Bulk status update
- CSV export stream
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, cast, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import (
    DuplicateError,
    NotFoundError,
    StateTransitionError,
)
from scvri_shared.kafka import get_producer
from scvri_shared.logging import get_logger
from scvri_shared.models.supplier import Certification, Contact, Supplier
from scvri_shared.outbox_relay import schedule_outbox_event
from supplier_management.schemas.supplier import (
    BulkSupplierStatusUpdate,
    CertificationCreate,
    ContactCreate,
    ContactUpdate,
    OnboardingTransitionRequest,
    SupplierCreate,
    SupplierSearchRequest,
    SupplierSummary,
    SupplierUpdate,
)

log = get_logger(__name__)


async def _emit_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    key: str | None = None,
) -> None:
    """Schedule event into Transactional Outbox and attempt producer dispatch."""
    await schedule_outbox_event(
        db,
        tenant_id=tenant_id,
        topic=topic,
        event_type=event_type,
        payload=payload,
        event_key=key,
    )
    try:
        async with get_producer() as producer:
            await producer.publish(
                topic=topic,
                key=key or str(tenant_id),
                value=payload,
                event_type=event_type,
                tenant_id=str(tenant_id),
            )
    except Exception as exc:
        log.debug("outbox.producer_direct_publish_deferred", error=str(exc))


# ---------------------------------------------------------------------------
# Valid onboarding state transitions
# ---------------------------------------------------------------------------
_ONBOARDING_FSM: dict[str, set[str]] = {
    "draft":        {"submitted"},
    "submitted":    {"under_review", "returned"},
    "under_review": {"approved", "returned", "rejected"},
    "returned":     {"submitted"},
    "approved":     {"active"},
    "rejected":     set(),
    "active":       {"suspended", "inactive"},
    "suspended":    {"active", "inactive"},
    "inactive":     set(),
}


# ---------------------------------------------------------------------------
# Supplier CRUD
# ---------------------------------------------------------------------------
async def create_supplier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: SupplierCreate,
) -> Supplier:
    """Create a new supplier with embedded contacts.

    Raises:
        DuplicateError: A supplier with the same name + country_code already exists.
    """
    # Uniqueness check within tenant (RLS already scoped)
    existing = await db.execute(
        select(Supplier.id).where(
            Supplier.name == data.name,
            Supplier.country_code == data.country_code,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateError("supplier", f"{data.name}/{data.country_code}")

    supplier = Supplier(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=data.name,
        legal_name=data.legal_name,
        tax_id=data.tax_id,
        country_code=data.country_code,
        address=data.address.model_dump() if data.address else None,
        website=str(data.website) if data.website else None,
        industry_code=data.industry_code,
        employee_count=data.employee_count,
        annual_revenue_usd=data.annual_revenue_usd,
        currency_code=data.currency_code,
        supplier_tier=data.supplier_tier,
        onboarding_status="draft",
        status="pending",
        tags=data.tags,
        diversity_info=data.diversity_info.model_dump() if data.diversity_info else None,
        custom_fields=data.custom_fields,
        created_by=user_id,
    )
    db.add(supplier)

    for c in data.contacts or []:
        db.add(Contact(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            first_name=c.first_name,
            last_name=c.last_name,
            email=c.email,
            phone=c.phone,
            title=c.title,
            department=c.department,
            is_primary=c.is_primary,
            is_portal_user=c.is_portal_user,
        ))

    await db.flush()

    # Emit event via Transactional Outbox
    await _emit_event(
        db,
        tenant_id=tenant_id,
        topic="supplier.events",
        event_type="supplier.created",
        payload={"supplier_id": str(supplier.id), "tenant_id": str(tenant_id)},
        key=str(supplier.id),
    )

    log.info("supplier.created", supplier_id=str(supplier.id), tenant_id=str(tenant_id))
    return supplier


async def get_supplier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> Supplier:
    """Fetch one supplier (raises NotFoundError if missing / wrong tenant)."""
    row = await db.execute(
        select(Supplier).where(Supplier.id == supplier_id)
    )
    supplier = row.scalar_one_or_none()
    if supplier is None or supplier.deleted_at is not None:
        raise NotFoundError("supplier", str(supplier_id))
    return supplier


async def update_supplier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
    data: SupplierUpdate,
) -> Supplier:
    """Partial update — only sets fields that are explicitly provided."""
    supplier = await get_supplier(db, tenant_id, supplier_id)

    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return supplier

    # Handle nested address
    if "address" in patch and patch["address"] is not None:
        patch["address"] = data.address.model_dump()

    if "diversity_info" in patch and patch["diversity_info"] is not None:
        patch["diversity_info"] = data.diversity_info.model_dump()

    for field, value in patch.items():
        setattr(supplier, field, value)

    supplier.updated_at = datetime.now(tz=timezone.utc)

    await _emit_event(
        db,
        tenant_id=tenant_id,
        topic="supplier.events",
        event_type="supplier.updated",
        payload={"supplier_id": str(supplier.id), "tenant_id": str(tenant_id), "fields": list(patch.keys())},
        key=str(supplier.id),
    )

    log.info("supplier.updated", supplier_id=str(supplier_id), fields=list(patch.keys()))
    return supplier


async def soft_delete_supplier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Soft-delete — marks deleted_at and status=inactive."""
    supplier = await get_supplier(db, tenant_id, supplier_id)
    supplier.deleted_at = datetime.now(tz=timezone.utc)
    supplier.status = "inactive"
    supplier.updated_at = datetime.now(tz=timezone.utc)

    await _emit_event(
        db,
        tenant_id=tenant_id,
        topic="supplier.events",
        event_type="supplier.deleted",
        payload={"supplier_id": str(supplier.id), "tenant_id": str(tenant_id)},
        key=str(supplier.id),
    )

    log.info("supplier.soft_deleted", supplier_id=str(supplier_id))


# ---------------------------------------------------------------------------
# Search / List
# ---------------------------------------------------------------------------
async def search_suppliers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    req: SupplierSearchRequest,
) -> tuple[list[Any], int]:
    """Full-text + filter search.

    Returns (rows, total_count).  Rows are Supplier ORM objects.
    """
    stmt = select(Supplier).where(Supplier.deleted_at.is_(None))

    # Full-text search
    if req.query:
        stmt = stmt.where(
            Supplier.search_tsv.op("@@")(
                func.plainto_tsquery("english", req.query)
            )
        )

    # Filters
    if req.status:
        stmt = stmt.where(Supplier.status.in_(req.status))
    if req.tier:
        stmt = stmt.where(Supplier.supplier_tier.in_(req.tier))
    if req.onboarding_status:
        stmt = stmt.where(Supplier.onboarding_status.in_(req.onboarding_status))
    if req.country_codes:
        stmt = stmt.where(Supplier.country_code.in_(req.country_codes))
    if req.tags:
        stmt = stmt.where(Supplier.tags.contains(req.tags))

    # Diversity flags
    if req.is_mbe:
        stmt = stmt.where(
            Supplier.diversity_info["is_mbe"].as_boolean() == True  # noqa: E712
        )
    if req.is_wbe:
        stmt = stmt.where(
            Supplier.diversity_info["is_wbe"].as_boolean() == True  # noqa: E712
        )
    if req.is_veteran_owned:
        stmt = stmt.where(
            Supplier.diversity_info["is_veteran_owned"].as_boolean() == True  # noqa: E712
        )

    # Count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Sorting
    _sort_columns = {
        "name": Supplier.name,
        "created_at": Supplier.created_at,
        "updated_at": Supplier.updated_at,
        "country_code": Supplier.country_code,
        "supplier_tier": Supplier.supplier_tier,
    }
    sort_col = _sort_columns.get(req.sort_by, Supplier.created_at)
    if req.sort_dir == "desc":
        sort_col = sort_col.desc()

    stmt = stmt.order_by(sort_col)
    stmt = stmt.offset((req.page - 1) * req.page_size).limit(req.page_size)

    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


# ---------------------------------------------------------------------------
# Onboarding state-machine
# ---------------------------------------------------------------------------
async def transition_onboarding(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
    req: OnboardingTransitionRequest,
) -> Supplier:
    """Apply an onboarding transition if it is valid."""
    supplier = await get_supplier(db, tenant_id, supplier_id)
    from_state = supplier.onboarding_status
    to_state = req.target_status

    allowed = _ONBOARDING_FSM.get(from_state, set())
    if to_state not in allowed:
        raise StateTransitionError(from_state, to_state, "supplier.onboarding_status")

    supplier.onboarding_status = to_state
    supplier.updated_at = datetime.now(tz=timezone.utc)

    # Cascade status changes
    if to_state == "active":
        supplier.status = "active"
    elif to_state in {"rejected", "inactive"}:
        supplier.status = "inactive"

    await _emit_event(
        db,
        tenant_id=tenant_id,
        topic="supplier.events",
        event_type="supplier.onboarding.transitioned",
        payload={
            "supplier_id": str(supplier.id),
            "tenant_id": str(tenant_id),
            "from_status": from_state,
            "to_status": to_state,
            "reason": req.reason,
            "metadata": req.metadata,
        },
        key=str(supplier.id),
    )

    log.info(
        "supplier.onboarding.transitioned",
        supplier_id=str(supplier_id),
        from_status=from_state,
        to_status=to_state,
    )
    return supplier


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------
async def bulk_update_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BulkSupplierStatusUpdate,
) -> int:
    """Set status on up to 100 suppliers at once.

    Returns the count of rows updated.
    """
    result = await db.execute(
        update(Supplier)
        .where(
            Supplier.id.in_(data.supplier_ids),
            Supplier.deleted_at.is_(None),
        )
        .values(
            status=data.status,
            updated_at=datetime.now(tz=timezone.utc),
        )
        .returning(Supplier.id)
    )
    updated_ids = result.scalars().all()
    count = len(updated_ids)

    await _emit_event(
        db,
        tenant_id=tenant_id,
        topic="supplier.events",
        event_type="supplier.bulk_status_updated",
        payload={
            "tenant_id": str(tenant_id),
            "supplier_ids": [str(i) for i in updated_ids],
            "new_status": data.status,
        },
        key=str(tenant_id),
    )

    log.info("supplier.bulk_update_status", count=count, new_status=data.status)
    return count


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
async def create_contact(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    data: ContactCreate,
) -> Contact:
    # Ensure supplier exists + belongs to tenant
    await get_supplier(db, tenant_id, supplier_id)

    # If new contact is primary, demote others
    if data.is_primary:
        await db.execute(
            update(Contact)
            .where(Contact.supplier_id == supplier_id, Contact.is_primary == True)  # noqa: E712
            .values(is_primary=False)
        )

    contact = Contact(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        title=data.title,
        department=data.department,
        is_primary=data.is_primary,
        is_portal_user=data.is_portal_user,
    )
    db.add(contact)
    await db.flush()
    return contact


async def list_contacts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> list[Contact]:
    await get_supplier(db, tenant_id, supplier_id)
    result = await db.execute(
        select(Contact).where(Contact.supplier_id == supplier_id)
    )
    return list(result.scalars().all())


async def update_contact(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    data: ContactUpdate,
) -> Contact:
    result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.supplier_id == supplier_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise NotFoundError("contact", str(contact_id))

    patch = data.model_dump(exclude_unset=True)
    if patch.get("is_primary"):
        await db.execute(
            update(Contact)
            .where(Contact.supplier_id == supplier_id, Contact.id != contact_id)
            .values(is_primary=False)
        )

    for field, value in patch.items():
        setattr(contact, field, value)

    return contact


async def delete_contact(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> None:
    result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.supplier_id == supplier_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise NotFoundError("contact", str(contact_id))
    await db.delete(contact)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------
async def create_certification(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CertificationCreate,
) -> Certification:
    await get_supplier(db, tenant_id, supplier_id)

    cert = Certification(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        certification_type=data.certification_type,
        certification_body=data.certification_body,
        certificate_number=data.certificate_number,
        issued_date=data.issued_date,
        expiry_date=data.expiry_date,
        scope=data.scope,
        status="active",
    )
    db.add(cert)
    await db.flush()
    return cert


async def list_certifications(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> list[Certification]:
    await get_supplier(db, tenant_id, supplier_id)
    result = await db.execute(
        select(Certification).where(Certification.supplier_id == supplier_id)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------
async def export_suppliers_csv(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> bytes:
    """Fetch all active suppliers and return a UTF-8 CSV as bytes."""
    result = await db.execute(
        select(Supplier).where(
            Supplier.deleted_at.is_(None),
            Supplier.status != "inactive",
        ).order_by(Supplier.name)
    )
    suppliers = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "name", "legal_name", "country_code", "industry_code",
        "supplier_tier", "status", "onboarding_status", "created_at",
    ])
    for s in suppliers:
        writer.writerow([
            str(s.id), s.name, s.legal_name, s.country_code, s.industry_code,
            s.supplier_tier, s.status, s.onboarding_status,
            s.created_at.isoformat() if s.created_at else "",
        ])

    return buf.getvalue().encode("utf-8")
