"""User management service — CRUD, status, password change."""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from iam.core.security import hash_password, verify_password
from iam.schemas.user import UserCreate, UserResponse, UserUpdate
from scvri_shared.exceptions import AuthenticationError, ConflictError, NotFoundError
from scvri_shared.logging import get_logger

log = get_logger(__name__)


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: UserCreate,
    created_by: uuid.UUID | None = None,
) -> UserResponse:
    # Uniqueness check within tenant
    existing = (await db.execute(text("""
        SELECT id FROM iam.users WHERE email = :email AND tenant_id = :tenant_id
    """), {"email": data.email.lower(), "tenant_id": str(tenant_id)})).scalar_one_or_none()

    if existing is not None:
        raise ConflictError(f"Email '{data.email}' already registered for this tenant")

    user_id = uuid.uuid4()
    pw_hash = hash_password(data.password)

    await db.execute(text("""
        INSERT INTO iam.users
            (id, tenant_id, email, full_name, password_hash, role, status,
             mfa_enabled, mfa_method, created_by, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :email, :full_name, :pw_hash, :role, 'active',
             FALSE, 'none', :created_by, now(), now())
    """), {
        "id": str(user_id),
        "tenant_id": str(tenant_id),
        "email": data.email.lower(),
        "full_name": data.full_name,
        "pw_hash": pw_hash,
        "role": data.role,
        "created_by": str(created_by) if created_by else None,
    })
    await db.commit()

    log.info("user.created", user_id=str(user_id), tenant_id=str(tenant_id))
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
    await get_user(db, tenant_id, user_id)
    await db.execute(text("""
        UPDATE iam.users SET status = 'inactive', updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(user_id), "tenant_id": str(tenant_id)})
    await db.commit()


# ── Password management ───────────────────────────────────────────────────────

async def change_password(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current_password: str,
    new_password: str,
) -> None:
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

def _map_user(row: dict) -> UserResponse:
    return UserResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        status=row["status"],
        mfa_method=row.get("mfa_method", "none"),
        mfa_enabled=bool(row.get("mfa_enabled", False)),
        last_login_at=row.get("last_login_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
