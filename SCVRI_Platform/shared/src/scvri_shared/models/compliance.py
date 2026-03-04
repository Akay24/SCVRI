"""Compliance models — GDPR erasure requests, CCPA rights, data processing records."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scvri_shared.models.base import (
    Base,
    TimestampMixin,
    TenantMixin,
    UUIDPrimaryKeyMixin,
)


ErasureStatus = Enum(
    "received",
    "scope_identified",
    "soft_deleted",
    "cascade_deleted",
    "pseudonymised",
    "completed",
    "partially_completed",
    "failed",
    "sla_escalated",
    name="erasure_status_enum",
    schema="compliance",
)

RightType = Enum(
    "erasure",          # GDPR Art. 17 / CCPA right to delete
    "access",           # GDPR Art. 15 / CCPA right to know
    "portability",      # GDPR Art. 20
    "rectification",    # GDPR Art. 16
    "restriction",      # GDPR Art. 18
    "objection",        # GDPR Art. 21
    "ccpa_opt_out",     # CCPA right to opt out of sale
    name="right_type_enum",
    schema="compliance",
)


class ErasureRequest(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """GDPR Art. 17 and CCPA deletion request.

    SLA: completed within 30 calendar days.
    computed column: sla_deadline = created_at + 30 days (set by trigger).

    7-step workflow:
        received → scope_identified → soft_deleted → cascade_deleted
        → pseudonymised → completed
    With SLA escalation via Celery Beat daily scan.
    """

    __tablename__ = "erasure_requests"
    __table_args__ = (
        Index("idx_erasure_tenant_status", "tenant_id", "status"),
        Index("idx_erasure_sla", "tenant_id", "sla_deadline", "status"),
        {"schema": "compliance"},
    )

    right_type: Mapped[str] = mapped_column(
        RightType, nullable=False, server_default="erasure"
    )
    status: Mapped[str] = mapped_column(
        ErasureStatus, nullable=False, server_default="received"
    )

    # ------------------------------------------------------------------ #
    # Data subject
    # ------------------------------------------------------------------ #
    data_subject_email: Mapped[str] = mapped_column(String(500), nullable=False)
    data_subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # NULL if external request (no platform account)
    requestor_name: Mapped[str | None] = mapped_column(String(400), nullable=True)
    requestor_email: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ------------------------------------------------------------------ #
    # SLA tracking
    # ------------------------------------------------------------------ #
    sla_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # set by DB trigger: created_at + 30d
    sla_escalated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # ------------------------------------------------------------------ #
    # Processing metadata
    # ------------------------------------------------------------------ #
    scope_summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # {tables, row_counts} identified during scope step
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # celery_worker | manual
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Retention exemption tracking
    # ------------------------------------------------------------------ #
    audit_retained: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )  # GDPR Art. 17(3)(b) — audit data pseudonymised but retained
    audit_retention_basis: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataProcessingRecord(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """GDPR Art. 30 records of processing activities (RoPA).

    One record per data processing category per tenant.
    """

    __tablename__ = "data_processing_records"
    __table_args__ = (
        Index("idx_dpa_tenant", "tenant_id"),
        {"schema": "compliance"},
    )

    processing_activity: Mapped[str] = mapped_column(String(300), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    legal_basis: Mapped[str] = mapped_column(
        Enum(
            "contract",
            "legitimate_interests",
            "consent",
            "legal_obligation",
            "vital_interests",
            "public_task",
            name="legal_basis_enum",
            schema="compliance",
        ),
        nullable=False,
    )
    data_categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    data_subjects: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    recipients: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    retention_period: Mapped[str] = mapped_column(String(100), nullable=False)
    third_country_transfers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    transfer_safeguards: Mapped[str | None] = mapped_column(Text, nullable=True)
    dpia_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    dpia_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ConsentRecord(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Consent records — captured when legal basis is 'consent'."""

    __tablename__ = "consent_records"
    __table_args__ = (
        Index("idx_consent_user", "tenant_id", "user_id"),
        {"schema": "compliance"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    consent_type: Mapped[str] = mapped_column(String(200), nullable=False)
    is_granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_text_version: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
