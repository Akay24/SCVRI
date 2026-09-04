"""IAM — Users, Roles, Sessions, Refresh Tokens, SSO Sessions.

Citus: users table distributed on tenant_id.
Security:
  - passwords hashed with bcrypt-12
  - refresh tokens stored as bcrypt hashes (never in plaintext)
  - FIDO2 credentials stored as JSONB blob
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scvri_shared.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    TenantMixin,
    UUIDPrimaryKeyMixin,
)
from scvri_shared.models.tenant import Tenant


SCVRI_ROLES = (
    "supply_chain_executive",
    "supply_chain_manager",
    "procurement_officer",
    "risk_analyst",
    "compliance_officer",
    "it_administrator",
    "ml_lead",
    "supplier_portal_user",
)


class User(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Platform user — supports password auth, SAML JIT, and OIDC."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        Index("idx_user_tenant_email", "tenant_id", "email"),
        {"schema": "auth"},
    )

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    email: Mapped[str] = mapped_column(String(500), nullable=False)
    first_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # ------------------------------------------------------------------ #
    # Authentication — password
    # ------------------------------------------------------------------ #
    password_hash: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # bcrypt-12; NULL for SSO-only users
    must_reset_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    previous_password_hashes: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # last 12 hashes for history check

    # ------------------------------------------------------------------ #
    # Authentication — SSO
    # ------------------------------------------------------------------ #
    sso_subject: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # IDP-provided subject identifier
    sso_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ------------------------------------------------------------------ #
    # MFA
    # ------------------------------------------------------------------ #
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mfa_type: Mapped[str | None] = mapped_column(
        Enum("totp", "fido2", "backup_code", name="mfa_type_enum", schema="auth"),
        nullable=True,
    )
    totp_secret_encrypted: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # KMS-encrypted TOTP secret
    fido2_credentials: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True
    )  # WebAuthn credential objects
    backup_codes_hash: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # 10 bcrypt-hashed backup codes

    # ------------------------------------------------------------------ #
    # Account security
    # ------------------------------------------------------------------ #
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_mfa_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6

    # ------------------------------------------------------------------ #
    # RBAC scoping (JWT claim injection)
    # ------------------------------------------------------------------ #
    procurement_categories: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # empty = unrestricted
    supplier_segments: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    geo_regions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # CCPA preference
    # ------------------------------------------------------------------ #
    ccpa_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="users", lazy="noload")
    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole", back_populates="user", lazy="noload", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken", back_populates="user", lazy="noload", cascade="all, delete-orphan"
    )


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Platform role definitions — system-wide (not tenant-scoped)."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_role_name"),
        {"schema": "auth"},
    )

    name: Mapped[str] = mapped_column(
        Enum(*SCVRI_ROLES, name="role_name_enum", schema="auth"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # resource → action mapping
    is_mfa_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )  # true for ml_lead, compliance_officer, it_administrator

    user_roles: Mapped[list[UserRole]] = relationship("UserRole", back_populates="role", lazy="noload")


class UserRole(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Association between user and role within a tenant."""

    __tablename__ = "user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["auth.users.id", "auth.users.tenant_id"],
            name="fk_userrole_user",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_user_role"),
        Index("idx_userrole_user", "tenant_id", "user_id"),
        {"schema": "auth"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth.roles.id"), nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="user_roles", lazy="noload")
    role: Mapped[Role] = relationship("Role", back_populates="user_roles", lazy="noload")


class RefreshToken(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Rotating refresh token store.

    The raw token is NEVER stored — only its bcrypt hash.
    JTI is stored in Redis for fast revocation checks (O(1) SET lookup).
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["auth.users.id", "auth.users.tenant_id"],
            name="fk_refresh_user",
            ondelete="CASCADE",
        ),
        Index("idx_refresh_user", "tenant_id", "user_id"),
        {"schema": "auth"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    jti: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )  # JWT ID — revocation key in Redis
    token_hash: Mapped[str] = mapped_column(String(200), nullable=False)  # bcrypt of raw token
    family: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # refresh token family (rotation fraud detection)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    device_fingerprint: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # browser/device hash for anomaly detection
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="refresh_tokens", lazy="noload")
