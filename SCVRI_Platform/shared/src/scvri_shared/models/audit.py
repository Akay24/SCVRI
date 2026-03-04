"""Audit Log model — immutable compliance trail.

Key properties:
  - Append-only enforced by PostgreSQL trigger (prevents UPDATE/DELETE)
  - Partitioned quarterly on event_time
  - Retention: 7 years (legal requirement)
  - actor_email is pseudonymised (not deleted) after GDPR erasure
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scvri_shared.models.base import Base, TenantMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TenantMixin):
    """Immutable audit log — one row per auditable event.

    Do NOT use ORM update() on this model — the DB trigger will raise.
    Always use INSERT only.

    Citus distribution: tenant_id.
    Partition key: event_time (quarterly).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_tenant_time", "tenant_id", "event_time"),
        Index("idx_audit_actor", "tenant_id", "actor_id"),
        Index("idx_audit_resource", "tenant_id", "resource_type", "resource_id"),
        {"schema": "audit"},
    )

    # ------------------------------------------------------------------ #
    # Actor
    # ------------------------------------------------------------------ #
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # NULL for system-generated events
    actor_email: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # pseudonymised after GDPR erasure
    actor_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    actor_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Event
    # ------------------------------------------------------------------ #
    event_type: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # e.g. "supplier.created", "risk_score.overridden", "user.login"
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )  # partition key
    correlation_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # X-Request-ID / trace ID

    # ------------------------------------------------------------------ #
    # Resource
    # ------------------------------------------------------------------ #
    resource_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # "supplier" | "user" | "alert" | etc.
    resource_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # UUID or other ID

    # ------------------------------------------------------------------ #
    # Change data
    # ------------------------------------------------------------------ #
    action: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # create | read | update | delete | login | logout | ...
    old_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Service attribution
    # ------------------------------------------------------------------ #
    service_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    service_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
