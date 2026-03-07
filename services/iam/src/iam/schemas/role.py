"""Role and permission schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import field_validator

from scvri_shared.schemas import CamelBase


class PermissionCreate(CamelBase):
    name: str                        # e.g. "alerts:write", "suppliers:read"
    description: str | None = None
    resource: str                    # e.g. "alerts", "suppliers", "risks"
    action: str                      # e.g. "read", "write", "admin"

    @field_validator("name", "resource", "action")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field cannot be blank")
        return v.strip().lower()


class PermissionResponse(CamelBase):
    id: uuid.UUID
    name: str
    description: str | None
    resource: str
    action: str
    created_at: datetime


class RoleCreate(CamelBase):
    name: str
    description: str | None = None
    permission_ids: list[uuid.UUID] = []

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be blank")
        return v.strip()


class RoleUpdate(CamelBase):
    description: str | None = None
    permission_ids: list[uuid.UUID] | None = None


class RoleResponse(CamelBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    permissions: list[PermissionResponse]
    user_count: int
    created_at: datetime
    updated_at: datetime


class RoleAssignRequest(CamelBase):
    user_id: uuid.UUID
    role_id: uuid.UUID
