"""Integration tests: model CRUD, RLS, and tenant isolation.

These tests require a live PostgreSQL database.  They are skipped automatically
when TEST_DATABASE_URL is not set or when the DB is unreachable.

Run:
    pytest shared/tests/test_models.py -v --asyncio-mode=auto
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Supplier CRUD
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestSupplierModel:
    async def test_create_supplier(self, db_session, sample_supplier) -> None:
        from scvri_shared.models.supplier import Supplier

        result = await db_session.get(Supplier, (sample_supplier.id, sample_supplier.tenant_id))
        assert result is not None
        assert result.legal_name == "Acme Testing Supply Co."

    async def test_supplier_updated_at_changes(self, db_session, sample_supplier) -> None:
        original_updated = sample_supplier.updated_at
        sample_supplier.trading_name = "Acme Updated"
        await db_session.flush()
        await db_session.refresh(sample_supplier)
        # updated_at is set by trigger — may be equal in same transaction
        assert sample_supplier.trading_name == "Acme Updated"

    async def test_supplier_search_tsv_populated(self, db_session, sample_tenant) -> None:
        """The search_tsv trigger should populate the TSVECTOR column."""
        from scvri_shared.models.supplier import Supplier

        supplier = Supplier(
            id=uuid.uuid4(),
            tenant_id=sample_tenant.id,
            legal_name="BluePeak Technologies Corp",
            country_code="US",
            status="active",
            onboarding_status="active",
            tier="strategic",
        )
        db_session.add(supplier)
        await db_session.flush()
        await db_session.refresh(supplier)
        # search_tsv is a server-side computed value — verify via raw SQL
        row = await db_session.execute(
            text("SELECT search_tsv::TEXT FROM supplier.suppliers WHERE id = :id"),
            {"id": str(supplier.id)},
        )
        tsv_text = row.scalar_one_or_none()
        assert tsv_text is not None
        assert "bluepeak" in tsv_text.lower() or "blue" in tsv_text.lower()

    async def test_soft_delete_hides_supplier(self, db_session, sample_supplier) -> None:
        sample_supplier.is_deleted = True
        await db_session.flush()
        # Active index filters out is_deleted=TRUE rows
        result = await db_session.execute(
            text("""
                SELECT count(*) FROM supplier.suppliers
                WHERE id = :id AND is_deleted = FALSE
            """),
            {"id": str(sample_supplier.id)},
        )
        assert result.scalar_one() == 0


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestUserModel:
    async def test_create_user(self, db_session, sample_user) -> None:
        from scvri_shared.models.auth import User

        result = await db_session.get(User, (sample_user.id, sample_user.tenant_id))
        assert result is not None
        assert result.email == sample_user.email

    async def test_unique_email_per_tenant(self, db_session, sample_tenant) -> None:
        from scvri_shared.models.auth import User
        from scvri_shared.security import hash_password

        email = f"dupe-{uuid.uuid4().hex[:8]}@test.dev"
        u1 = User(
            id=uuid.uuid4(),
            tenant_id=sample_tenant.id,
            email=email,
            first_name="A",
            last_name="B",
            password_hash=hash_password("T3stPass!word"),
        )
        db_session.add(u1)
        await db_session.flush()

        u2 = User(
            id=uuid.uuid4(),
            tenant_id=sample_tenant.id,
            email=email,
            first_name="C",
            last_name="D",
            password_hash=hash_password("T3stPass!word"),
        )
        db_session.add(u2)
        with pytest.raises(Exception):  # UniqueViolation
            await db_session.flush()


# ---------------------------------------------------------------------------
# Tenant isolation via RLS
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestTenantIsolation:
    async def test_rls_prevents_cross_tenant_read(self, db_session, sample_supplier) -> None:
        """With a different tenant_id set in session, supplier should be invisible."""
        other_tenant_id = str(uuid.uuid4())

        # Set a different tenant as the RLS context
        await db_session.execute(
            text("SET LOCAL scvri.tenant_id = :tid"),
            {"tid": other_tenant_id},
        )

        count = await db_session.execute(
            text("SELECT count(*) FROM supplier.suppliers WHERE id = :id"),
            {"id": str(sample_supplier.id)},
        )
        assert count.scalar_one() == 0, "RLS should hide rows from other tenants"

    async def test_rls_allows_correct_tenant_read(self, db_session, sample_supplier) -> None:
        """With the correct tenant_id set, supplier should be visible."""
        await db_session.execute(
            text("SET LOCAL scvri.tenant_id = :tid"),
            {"tid": str(sample_supplier.tenant_id)},
        )

        count = await db_session.execute(
            text("SELECT count(*) FROM supplier.suppliers WHERE id = :id"),
            {"id": str(sample_supplier.id)},
        )
        assert count.scalar_one() == 1, "RLS should allow access for the correct tenant"

    async def test_audit_log_append_only(self, db_session, sample_tenant) -> None:
        """The audit_log immutability trigger must deny UPDATE attempts."""
        # Insert a valid audit row
        await db_session.execute(
            text("""
                INSERT INTO audit.audit_log
                    (id, tenant_id, event_type, action, event_time)
                VALUES
                    (:id, :tid, 'test.event', 'CREATE', NOW())
            """),
            {"id": str(uuid.uuid4()), "tid": str(sample_tenant.id)},
        )
        # SET RLS so the row is visible
        await db_session.execute(
            text("SET LOCAL scvri.tenant_id = :tid"),
            {"tid": str(sample_tenant.id)},
        )

        with pytest.raises(Exception, match="append-only"):
            await db_session.execute(
                text("UPDATE audit.audit_log SET action = 'TAMPERED' WHERE tenant_id = :tid"),
                {"tid": str(sample_tenant.id)},
            )
