"""User and tenant membership schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, field_validator

from scvri_shared.schemas import CamelBase

# ── Enums ─────────────────────────────────────────────────────────────────────

UserStatus = Literal["active", "inactive", "suspended", "pending_mfa"]

MFAMethod = Literal["totp", "none"]

# Platform-level roles (stored on tenant_memberships.role)
PlatformRole = Literal[
    "it_administrator",
    "supply_chain_manager",
    "procurement_officer",
    "risk_analyst",
    "viewer",
]


# ── User schemas ──────────────────────────────────────────────────────────────

class UserCreate(CamelBase):
    email: EmailStr
    full_name: str
    password: str
    role: PlatformRole = "viewer"
    tenant_id: uuid.UUID | None = None    # assigned by admin; omitted in self-registration

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain at least one digit")
        return v

    @field_validator("full_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("full_name cannot be blank")
        return v.strip()


class UserUpdate(CamelBase):
    full_name: str | None = None
    role: PlatformRole | None = None
    status: UserStatus | None = None
    mfa_method: MFAMethod | None = None


class UserResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str
    role: PlatformRole
    status: UserStatus
    mfa_method: MFAMethod
    mfa_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserPasswordChange(CamelBase):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("password must contain at least one digit")
        return v


class UserPasswordReset(CamelBase):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


# ── Tenant membership ──────────────────────────────────────────────────────────

class TenantMemberCreate(CamelBase):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: PlatformRole


class TenantMemberResponse(CamelBase):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: PlatformRole
    joined_at: datetime


# ── SCIM-compatible user (RFC 7643) ───────────────────────────────────────────

class SCIMUserName(CamelBase):
    formatted: str | None = None
    given_name: str | None = None
    family_name: str | None = None


class SCIMEmail(CamelBase):
    value: str
    primary: bool = True
    type: str = "work"


class SCIMUserCreate(CamelBase):
    """SCIM 2.0 User resource (simplified for SCVRI provisioning)."""
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    user_name: str          # maps to email
    name: SCIMUserName | None = None
    emails: list[SCIMEmail] = []
    active: bool = True
    external_id: str | None = None      # IdP external identifier


class SCIMUserResponse(CamelBase):
    """SCIM 2.0 User response resource."""
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    id: str
    external_id: str | None
    user_name: str
    name: SCIMUserName | None
    emails: list[SCIMEmail]
    active: bool
    meta: dict


class SCIMListResponse(CamelBase):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:ListResponse"]
    total_results: int
    start_index: int = 1
    items_per_page: int
    resources: list[SCIMUserResponse]
