"""Users router — CRUD and password management."""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from iam.dependencies import AdminDep, CurrentUserDep, TenantDbDep, WriteDep
from iam.schemas.user import UserCreate, UserPasswordChange, UserResponse, UserUpdate
from iam.services import user_service
from scvri_shared.exceptions import AuthenticationError, ConflictError, NotFoundError

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: TenantDbDep,
    claims: CurrentUserDep,
    user_status: Optional[str] = Query(None, alias="status"),
    role: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[UserResponse]:
    return await user_service.list_users(
        db, claims.tenant_id,
        status=user_status, role=role, limit=limit, offset=offset,
    )


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: TenantDbDep,
    claims: AdminDep,
) -> UserResponse:
    """Create a new user (admin only)."""
    try:
        return await user_service.create_user(db, claims.tenant_id, data, claims.user_id)
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: TenantDbDep,
    claims: CurrentUserDep,
) -> UserResponse:
    # Users can view themselves; admins can view anyone
    if claims.user_id != user_id and claims.role not in {"it_administrator"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    try:
        return await user_service.get_user(db, claims.tenant_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: TenantDbDep,
    claims: AdminDep,
) -> UserResponse:
    """Update user attributes (admin only)."""
    try:
        return await user_service.update_user(db, claims.tenant_id, user_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    db: TenantDbDep,
    claims: AdminDep,
) -> None:
    """Deactivate a user account (admin only)."""
    try:
        await user_service.delete_user(db, claims.tenant_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    user_id: uuid.UUID,
    data: UserPasswordChange,
    db: TenantDbDep,
    claims: CurrentUserDep,
) -> None:
    """Change own password — user must provide current password."""
    if claims.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    try:
        await user_service.change_password(
            db, claims.tenant_id, user_id,
            data.current_password, data.new_password,
        )
    except (NotFoundError, AuthenticationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
