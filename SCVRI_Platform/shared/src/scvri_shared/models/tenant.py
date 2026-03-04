"""Tenant model — top-level isolation boundary for all platform data."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scvri_shared.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from scvri_shared.models.supplier import Supplier
    from scvri_shared.models.auth import User


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Enterprise tenant — one row per SCVRI customer organisation.

    Citus: this table is NOT distributed (small lookup table; kept on all nodes
    via reference table distribution):
        SELECT create_reference_table('platform.tenants');
    """

    __tablename__ = "tenants"
    __table_args__ = {"schema": "platform"}

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )  # e.g. "acme-corp" — used in API paths and JWT sub claims
    domain: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # verified email domain for SSO enforcement

    # ------------------------------------------------------------------ #
    # Subscription
    # ------------------------------------------------------------------ #
    plan: Mapped[str] = mapped_column(
        Enum("starter", "professional", "enterprise", name="tenant_plan_enum"),
        nullable=False,
        server_default="enterprise",
    )
    max_suppliers: Mapped[int] = mapped_column(nullable=False, server_default="10000")
    max_users: Mapped[int] = mapped_column(nullable=False, server_default="500")
    api_rate_limit_per_minute: Mapped[int] = mapped_column(
        nullable=False, server_default="2000"
    )

    # ------------------------------------------------------------------ #
    # Data Residency (GDPR)
    # ------------------------------------------------------------------ #
    data_region: Mapped[str] = mapped_column(
        Enum("us-east-1", "eu-west-1", name="aws_region_enum"),
        nullable=False,
        server_default="us-east-1",
    )

    # ------------------------------------------------------------------ #
    # SSO / Identity Provider Config
    # ------------------------------------------------------------------ #
    sso_enabled: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    sso_provider: Mapped[str | None] = mapped_column(
        Enum("saml", "oidc", name="sso_provider_enum"), nullable=True
    )
    sso_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # SAML metadata URL / OIDC discovery config

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    users: Mapped[list[User]] = relationship(
        "User", back_populates="tenant", lazy="noload"
    )
    suppliers: Mapped[list[Supplier]] = relationship(
        "Supplier", back_populates="tenant", lazy="noload"
    )
