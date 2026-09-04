"""User management service — CRUD, status, password change."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from iam.core.security import hash_password, verify_password
from iam.schemas.user import UserCreate, UserPasswordChange, UserResponse, UserUpdate
from scvri_shared.exceptions import AuthenticationError, ConflictError, NotFoundError
from scvri_shared.logging import get_logger

log = get_logger(__name__)


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_user(
    db: AsyncSession,
    tenant_id_or_data: uuid.UUID | UserCreate,
    data: UserCreate | None = None,
    created_by: uuid.UUID | None = None,
) -> UserResponse:
    if isinstance(tenant_id_or_data, UserCreate):
        user_create = tenant_id_or_data
        tenant_id = user_create.tenant_id
        if tenant_id is None:
            raise ValueError("tenant_id must be provided on UserCreate payload")
    else:
        tenant_id = tenant_id_or_data
        user_create = data
        if user_create is None:
            raise ValueError("data must be provided")

    user_id = uuid.uuid4()
    pw_hash = hash_password(user_create.password)

    try:
        result = await db.execute(text("""
            INSERT INTO iam.users
                (id, tenant_id, email, full_name, password_hash, role, status,
                 mfa_enabled, mfa_method, created_by, created_at, updated_at)
            VALUES
                (:id, :tenant_id, :email, :full_name, :pw_hash, :role, 'active',
                 FALSE, 'none', :created_by, now(), now())
            RETURNING id, tenant_id, email, full_name, role, status,
                      mfa_enabled, mfa_method, created_by, created_at, updated_at
        """), {
            "id": str(user_id),
            "tenant_id": str(tenant_id),
            "email": user_create.email.lower(),
            "full_name": user_create.full_name,
            "pw_hash": pw_hash,
            "role": user_create.role,
            "created_by": str(created_by) if created_by else None,
        })
        await db.commit()
    except IntegrityError as exc:
        raise ConflictError(f"Email '{user_create.email}' already registered for this tenant") from exc

    log.info("user.created", user_id=str(user_id), tenant_id=str(tenant_id))

    if hasattr(result, "mappings"):
        mappings = result.mappings()
        if hasattr(mappings, "one"):
            row = mappings.one()
            return _map_user(row)
        elif hasattr(mappings, "one_or_none"):
            row = mappings.one_or_none()
            if row:
                return _map_user(row)

    return await get_user(db, tenant_id, user_id)


async def get_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> UserResponse:
    row = (await db.execute(text("""
        SELECT * FROM iam.users WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(user_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"User {user_id} not found")
    return _map_user(row)


async def get_user_by_email(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
) -> UserResponse | None:
    row = (await db.execute(text("""
        SELECT * FROM iam.users WHERE email = :email AND tenant_id = :tenant_id
    """), {"email": email.lower(), "tenant_id": str(tenant_id)})).mappings().one_or_none()
    return _map_user(row) if row else None


async def list_users(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    status: str | None = None,
    role: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[UserResponse]:
    conditions = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": str(tenant_id), "limit": limit, "offset": offset}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if role:
        conditions.append("role = :role")
        params["role"] = role

    where = " AND ".join(conditions)
    rows = (await db.execute(text(f"""
        SELECT * FROM iam.users
        WHERE {where}
        ORDER BY full_name
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    return [_map_user(r) for r in rows]


async def update_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UserUpdate,
) -> UserResponse:
    await get_user(db, tenant_id, user_id)

    sets = ["updated_at = now()"]
    params: dict = {"id": str(user_id), "tenant_id": str(tenant_id)}

    if data.full_name is not None:
        sets.append("full_name = :full_name"); params["full_name"] = data.full_name
    if data.role is not None:
        sets.append("role = :role"); params["role"] = data.role
    if data.status is not None:
        sets.append("status = :status"); params["status"] = data.status

    await db.execute(text(f"""
        UPDATE iam.users SET {', '.join(sets)}
        WHERE id = :id AND tenant_id = :tenant_id
    """), params)
    await db.commit()
    return await get_user(db, tenant_id, user_id)


async def delete_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Soft-delete — set status to inactive."""
    result = await db.execute(text("""
        UPDATE iam.users SET status = 'inactive', updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(user_id), "tenant_id": str(tenant_id)})
    if getattr(result, "rowcount", None) == 0:
        raise NotFoundError(f"User {user_id} not found")
    await db.commit()


# ── Password management ───────────────────────────────────────────────────────

async def change_password(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_password_or_data: str | UserPasswordChange,
    new_password: str | None = None,
) -> None:
    if isinstance(current_password_or_data, UserPasswordChange):
        current_password = current_password_or_data.current_password
        new_password = current_password_or_data.new_password
    else:
        current_password = current_password_or_data
        if new_password is None:
            raise ValueError("new_password must be provided")

    row = (await db.execute(text("""
        SELECT password_hash FROM iam.users
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(user_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError("User not found")
    if not verify_password(current_password, row["password_hash"]):
        raise AuthenticationError("Current password is incorrect")

    new_hash = hash_password(new_password)
    await db.execute(text("""
        UPDATE iam.users
        SET password_hash = :hash, updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"hash": new_hash, "id": str(user_id), "tenant_id": str(tenant_id)})
    await db.commit()


# ── Mapper ────────────────────────────────────────────────────────────────────

def _map_user(row: dict | Any) -> UserResponse:
    def get_val(key: str, default: Any = None) -> Any:
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    return UserResponse(
        id=get_val("id"),
        tenant_id=get_val("tenant_id"),
        email=get_val("email"),
        full_name=get_val("full_name"),
        role=get_val("role"),
        status=get_val("status"),
        mfa_method=get_val("mfa_method", "none"),
        mfa_enabled=bool(get_val("mfa_enabled", False)),
        last_login_at=get_val("last_login_at"),
        created_at=get_val("created_at"),
        updated_at=get_val("updated_at"),
    )
