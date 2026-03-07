"""Roles & permissions router — custom RBAC."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from iam.dependencies import AdminDep, CurrentUserDep, TenantDbDep
from iam.schemas.role import (
    PermissionCreate,
    PermissionResponse,
    RoleAssignRequest,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from iam.services import role_service
from scvri_shared.exceptions import ConflictError, NotFoundError

router = APIRouter(tags=["roles"])


# ── Permissions ───────────────────────────────────────────────────────────────

@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    db: TenantDbDep,
    claims: CurrentUserDep,
) -> list[PermissionResponse]:
    return await role_service.list_permissions(db, claims.tenant_id)


@router.post(
    "/permissions",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_permission(
    data: PermissionCreate,
    db: TenantDbDep,
    claims: AdminDep,
) -> PermissionResponse:
    try:
        return await role_service.create_permission(db, claims.tenant_id, data)
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    db: TenantDbDep,
    claims: CurrentUserDep,
) -> list[RoleResponse]:
    return await role_service.list_roles(db, claims.tenant_id)


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    db: TenantDbDep,
    claims: AdminDep,
) -> RoleResponse:
    try:
        return await role_service.create_role(db, claims.tenant_id, data)
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: uuid.UUID,
    db: TenantDbDep,
    claims: CurrentUserDep,
) -> RoleResponse:
    try:
        return await role_service.get_role(db, claims.tenant_id, role_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    data: RoleUpdate,
    db: TenantDbDep,
    claims: AdminDep,
) -> RoleResponse:
    try:
        return await role_service.update_role(db, claims.tenant_id, role_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    db: TenantDbDep,
    claims: AdminDep,
) -> None:
    try:
        await role_service.delete_role(db, claims.tenant_id, role_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/roles/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign_role(
    data: RoleAssignRequest,
    db: TenantDbDep,
    claims: AdminDep,
) -> None:
    """Assign a custom role to a user."""
    try:
        await role_service.assign_role(db, claims.tenant_id, data.user_id, data.role_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
