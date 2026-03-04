"""Risk Intelligence models.

Covers: supplier_risk_scores, kri_definitions, kri_snapshots, risk_rules,
        external_data_feeds, risk_score_overrides.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scvri_shared.models.base import (
    Base,
    TimestampMixin,
    TenantMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from scvri_shared.models.supplier import Supplier


RiskLevel = Enum(
    "critical",
    "high",
    "medium",
    "low",
    name="risk_level_enum",
    schema="risk",
)


class SupplierRiskScore(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Latest risk score for each supplier.

    The score history is in ``risk_score_history`` (partitioned quarterly).
    This table always holds the current production score.
    Citus distribution: tenant_id.
    """

    __tablename__ = "supplier_risk_scores"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "supplier_id", name="uq_risk_score_tenant_supplier"
        ),
        ForeignKeyConstraint(
            ["supplier_id", "tenant_id"],
            ["supplier.suppliers.id", "supplier.suppliers.tenant_id"],
            name="fk_risk_score_supplier",
        ),
        Index("idx_risk_supplier", "tenant_id", "supplier_id"),
        Index("idx_risk_level", "tenant_id", "risk_level"),
        Index("idx_risk_score_value", "tenant_id", "composite_score"),
        {"schema": "risk"},
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # ------------------------------------------------------------------ #
    # Composite score (0-100, higher = riskier)
    # ------------------------------------------------------------------ #
    composite_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    risk_level: Mapped[str] = mapped_column(RiskLevel, nullable=False)

    # ------------------------------------------------------------------ #
    # Component scores
    # ------------------------------------------------------------------ #
    financial_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    operational_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    geopolitical_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    esg_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    delivery_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # ------------------------------------------------------------------ #
    # ML model metadata
    # ------------------------------------------------------------------ #
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # MLflow run ID
    features_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # 87-feature vector for reproducibility
    shap_values: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # top-N SHAP factor explanations

    # ------------------------------------------------------------------ #
    # Override tracking
    # ------------------------------------------------------------------ #
    is_overridden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    override_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ------------------------------------------------------------------ #
    # Scoring timestamps
    # ------------------------------------------------------------------ #
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    next_scheduled_rescore: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    supplier: Mapped[Supplier] = relationship(
        "Supplier", back_populates="risk_scores", lazy="noload"
    )


class RiskScoreHistory(Base, UUIDPrimaryKeyMixin, TenantMixin):
    """Immutable historical record of every risk score change.

    Partitioned by ``scored_at`` quarterly.
    Retention: 3 years hot → indefinite cold (S3 via Kafka S3 Sink).
    """

    __tablename__ = "risk_score_history"
    __table_args__ = (
        Index("idx_risk_hist_supplier_time", "tenant_id", "supplier_id", "scored_at"),
        {"schema": "risk"},
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    composite_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risk_level: Mapped[str] = mapped_column(RiskLevel, nullable=False)
    trigger_event: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g. "kafka_event", "scheduled_batch", "manual"
    trigger_event_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # Kafka message ID or batch ID
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # partition key


class KRIDefinition(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Key Risk Indicator definitions — configurable per tenant."""

    __tablename__ = "kri_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kri_code", name="uq_kri_tenant_code"),
        {"schema": "risk"},
    )

    kri_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # financial | operational | geopolitical | esg | delivery
    unit: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # percentage | days | count | score
    warning_threshold: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    critical_threshold: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    threshold_direction: Mapped[str] = mapped_column(
        Enum("above", "below", name="threshold_dir_enum", schema="risk"),
        nullable=False,
        server_default="above",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    weight_in_composite: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default="0.000"
    )
    snapshots: Mapped[list[KRISnapshot]] = relationship(
        "KRISnapshot", back_populates="definition", lazy="noload"
    )


class KRISnapshot(Base, UUIDPrimaryKeyMixin, TenantMixin):
    """Periodic KRI measurement for a supplier.

    Partitioned by ``snapshot_date`` quarterly.
    """

    __tablename__ = "kri_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["kri_id", "tenant_id"],
            ["risk.kri_definitions.id", "risk.kri_definitions.tenant_id"],
            name="fk_kri_snapshot_def",
        ),
        Index(
            "idx_kri_snapshot_supplier_date",
            "tenant_id",
            "supplier_id",
            "snapshot_date",
        ),
        {"schema": "risk"},
    )

    kri_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )  # partition key
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    breach_level: Mapped[str | None] = mapped_column(
        Enum("warning", "critical", name="breach_level_enum", schema="risk"), nullable=True
    )
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    definition: Mapped[KRIDefinition] = relationship(
        "KRIDefinition", back_populates="snapshots", lazy="noload"
    )


class RiskRule(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """CEP-style rule definitions for the Alert Engine."""

    __tablename__ = "risk_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "rule_code", name="uq_rule_tenant_code"),
        {"schema": "risk"},
    )

    rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )  # true = platform-defined, immutable
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # ------------------------------------------------------------------ #
    # Rule definition (interpreted by the Alert Engine CEP evaluator)
    # ------------------------------------------------------------------ #
    condition_dsl: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # structured DSL: {field, operator, value, window_seconds, count}
    severity: Mapped[str] = mapped_column(RiskLevel, nullable=False)
    alert_title_template: Mapped[str] = mapped_column(String(500), nullable=False)
    alert_body_template: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_actions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Throttling
    # ------------------------------------------------------------------ #
    dedup_window_seconds: Mapped[int] = mapped_column(
        nullable=False, server_default="3600"
    )  # default 1h dedup window

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
