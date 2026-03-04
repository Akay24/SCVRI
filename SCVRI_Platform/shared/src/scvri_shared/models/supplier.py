"""Supplier domain models.

Covers: suppliers, supplier_contacts, supplier_certifications,
        supplier_documents, supplier_scorecards, supplier_diversity_flags.

Citus distribution key: tenant_id (shards supplier data per tenant across workers).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scvri_shared.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    TenantMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from scvri_shared.models.tenant import Tenant
    from scvri_shared.models.purchase_order import PurchaseOrder
    from scvri_shared.models.risk import SupplierRiskScore


# ============================================================
# Enums
# ============================================================
OnboardingStatus = Enum(
    "pending_onboarding",
    "questionnaire_sent",
    "questionnaire_in_progress",
    "documents_requested",
    "under_review",
    "compliance_check",
    "approved",
    "rejected",
    "active",
    name="onboarding_status_enum",
    schema="supplier",
)

SupplierStatus = Enum(
    "draft",
    "active",
    "suspended",
    "deactivated",
    "banned",
    name="supplier_status_enum",
    schema="supplier",
)

SupplierTier = Enum(
    "strategic",
    "preferred",
    "standard",
    "one_time",
    name="supplier_tier_enum",
    schema="supplier",
)

ScoreGrade = Enum("A", "B", "C", "D", name="score_grade_enum", schema="supplier")


# ============================================================
# Supplier
# ============================================================
class Supplier(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Core supplier record — 10,000 per enterprise tenant.

    DDL note: Citus shards this table on tenant_id.
    Full-text search column ``search_tsv`` is populated by a trigger.
    """

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "duns_number", name="uq_supplier_tenant_duns"),
        UniqueConstraint("tenant_id", "tax_id", name="uq_supplier_tenant_tax_id"),
        Index("idx_suppliers_tenant_name", "tenant_id", "legal_name"),
        Index(
            "idx_suppliers_search_tsv",
            "search_tsv",
            postgresql_using="gin",
        ),
        {"schema": "supplier"},
    )

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    legal_name: Mapped[str] = mapped_column(String(500), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duns_number: Mapped[str | None] = mapped_column(String(9), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ------------------------------------------------------------------ #
    # Classification
    # ------------------------------------------------------------------ #
    status: Mapped[str] = mapped_column(
        SupplierStatus, nullable=False, server_default="draft"
    )
    onboarding_status: Mapped[str] = mapped_column(
        OnboardingStatus, nullable=False, server_default="pending_onboarding"
    )
    tier: Mapped[str] = mapped_column(
        SupplierTier, nullable=False, server_default="standard"
    )
    primary_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    secondary_categories: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(200)), nullable=True
    )
    commodity_codes: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(20)), nullable=True
    )  # UNSPSC or custom codes

    # ------------------------------------------------------------------ #
    # Geography
    # ------------------------------------------------------------------ #
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False
    )  # ISO 3166-1 alpha-2
    state_province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address_line_1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    geo_region: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g. APAC, EMEA, AMER

    # ------------------------------------------------------------------ #
    # Financial
    # ------------------------------------------------------------------ #
    annual_revenue_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_rating: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ------------------------------------------------------------------ #
    # Diversity classification (RISK-FR-013 / alternate pool)
    # ------------------------------------------------------------------ #
    is_wbe: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_mbe: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_lgbtbe: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_veteran_owned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_disability_owned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_hbcu_affiliated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # ------------------------------------------------------------------ #
    # Full-text search
    # ------------------------------------------------------------------ #
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, nullable=True
    )  # populated by DB trigger

    # ------------------------------------------------------------------ #
    # External IDs (ERP integration)
    # ------------------------------------------------------------------ #
    erp_vendor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    erp_system: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # sap | oracle_fusion | dynamics365

    # ------------------------------------------------------------------ #
    # Additional metadata
    # ------------------------------------------------------------------ #
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="suppliers", lazy="noload")
    contacts: Mapped[list[SupplierContact]] = relationship(
        "SupplierContact",
        back_populates="supplier",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    certifications: Mapped[list[SupplierCertification]] = relationship(
        "SupplierCertification",
        back_populates="supplier",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[SupplierDocument]] = relationship(
        "SupplierDocument",
        back_populates="supplier",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    scorecards: Mapped[list[SupplierScorecard]] = relationship(
        "SupplierScorecard",
        back_populates="supplier",
        lazy="noload",
        order_by="SupplierScorecard.period_end.desc()",
    )
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(
        "PurchaseOrder", back_populates="supplier", lazy="noload"
    )
    risk_scores: Mapped[list[SupplierRiskScore]] = relationship(
        "SupplierRiskScore", back_populates="supplier", lazy="noload"
    )


# ============================================================
# Supplier Contact
# ============================================================
class SupplierContact(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Named contacts for a supplier (primary, commercial, technical, etc.)."""

    __tablename__ = "supplier_contacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_contact_supplier",
            ondelete="CASCADE",
        ),
        Index("idx_contacts_supplier", "tenant_id", "supplier_id"),
        {"schema": "supplier"},
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_type: Mapped[str] = mapped_column(
        Enum(
            "primary",
            "commercial",
            "technical",
            "legal",
            "sustainability",
            name="contact_type_enum",
            schema="supplier",
        ),
        nullable=False,
        server_default="primary",
    )
    first_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # ------------------------------------------------------------------ #
    # GDPR — personal data flag for erasure workflow
    # ------------------------------------------------------------------ #
    is_erased: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="contacts", lazy="noload")


# ============================================================
# Supplier Certification
# ============================================================
class SupplierCertification(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """ISO, regulatory, and industry certifications with expiry tracking."""

    __tablename__ = "supplier_certifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_cert_supplier",
            ondelete="CASCADE",
        ),
        Index("idx_certs_supplier", "tenant_id", "supplier_id"),
        Index("idx_certs_expiry", "tenant_id", "expiry_date"),
        {"schema": "supplier"},
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cert_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # ISO9001, ISO14001, SOC2, etc.
    cert_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issuing_body: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # FK → supplier_documents

    supplier: Mapped[Supplier] = relationship(
        "Supplier", back_populates="certifications", lazy="noload"
    )


# ============================================================
# Supplier Document (S3-backed vault)
# ============================================================
class SupplierDocument(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Document vault entry — metadata record; file stored in S3.

    S3 key: ``{tenant_id}/suppliers/{supplier_id}/docs/{id}/{filename}``
    Object Lock COMPLIANCE mode, 7-year retention.
    """

    __tablename__ = "supplier_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_doc_supplier",
            ondelete="CASCADE",
        ),
        Index("idx_docs_supplier", "tenant_id", "supplier_id"),
        {"schema": "supplier"},
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    s3_bucket: Mapped[str] = mapped_column(String(200), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    s3_version_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    document_type: Mapped[str] = mapped_column(
        Enum(
            "certification",
            "financial_statement",
            "insurance",
            "questionnaire",
            "contract",
            "other",
            name="document_type_enum",
            schema="supplier",
        ),
        nullable=False,
        server_default="other",
    )
    upload_status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "scanning",
            "clean",
            "infected",
            "failed",
            name="doc_upload_status_enum",
            schema="supplier",
        ),
        nullable=False,
        server_default="pending",
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="documents", lazy="noload")


# ============================================================
# Supplier Scorecard
# ============================================================
class SupplierScorecard(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Quarterly SCOR-model performance scorecard.

    Formulas:
      otd_rate         = on_time_deliveries    / total_deliveries
      defect_rate      = returned_items        / items_received
      fill_rate        = items_received        / items_ordered
      invoice_accuracy = 100 - invoice_discrepancy_pct
      overall_score    = 0.35*otd + 0.25*fill + 0.25*(1-defect) + 0.15*invoice_accuracy
    """

    __tablename__ = "supplier_scorecards"
    __table_args__ = (
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_scorecard_supplier",
            ondelete="CASCADE",
        ),
        Index("idx_scorecard_supplier_period", "tenant_id", "supplier_id", "period_end"),
        {"schema": "supplier"},
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # ---- Raw counters ------------------------------------------------- #
    total_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    on_time_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_ordered: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    items_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    returned_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    invoice_discrepancy_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0.00"
    )

    # ---- Computed scores ---------------------------------------------- #
    otd_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0.0000"
    )
    defect_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0.0000"
    )
    fill_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0.0000"
    )
    invoice_accuracy: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="100.00"
    )
    overall_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0.00"
    )
    grade: Mapped[str] = mapped_column(ScoreGrade, nullable=False, server_default="D")

    # ---- Metadata ----------------------------------------------------- #
    formula_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="1.0"
    )
    computed_by: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="celery_worker"
    )

    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="scorecards", lazy="noload")
