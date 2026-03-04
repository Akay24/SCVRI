"""Role and permission service — custom RBAC per tenant."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from iam.schemas.role import (
    PermissionCreate,
    PermissionResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from scvri_shared.exceptions import ConflictError, NotFoundError
from scvri_shared.logging import get_logger

log = get_logger(__name__)


# ── Permissions ───────────────────────────────────────────────────────────────

async def create_permission(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PermissionCreate,
) -> PermissionResponse:
    # Check unique name within tenant
    exists = (await db.execute(text("""
        SELECT id FROM iam.permissions WHERE name = :name AND tenant_id = :tenant_id
    """), {"name": data.name, "tenant_id": str(tenant_id)})).scalar_one_or_none()
    if exists:
        raise ConflictError(f"Permission '{data.name}' already exists")

    perm_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO iam.permissions (id, tenant_id, name, description, resource, action, created_at)
        VALUES (:id, :tenant_id, :name, :desc, :resource, :action, now())
    """), {
        "id": str(perm_id), "tenant_id": str(tenant_id),
        "name": data.name, "desc": data.description,
        "resource": data.resource, "action": data.action,
    })
    await db.commit()
    return await get_permission(db, tenant_id, perm_id)


async def get_permission(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    perm_id: uuid.UUID,
) -> PermissionResponse:
    row = (await db.execute(text("""
        SELECT * FROM iam.permissions WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(perm_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()
    if row is None:
        raise NotFoundError(f"Permission {perm_id} not found")
    return PermissionResponse(
        id=row["id"], name=row["name"], description=row.get("description"),
        resource=row["resource"], action=row["action"], created_at=row["created_at"],
    )


async def list_permissions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[PermissionResponse]:
    rows = (await db.execute(text("""
        SELECT * FROM iam.permissions WHERE tenant_id = :tenant_id ORDER BY name
    """), {"tenant_id": str(tenant_id)})).mappings().all()
    return [
        PermissionResponse(
            id=r["id"], name=r["name"], description=r.get("description"),
            resource=r["resource"], action=r["action"], created_at=r["created_at"],
        )
        for r in rows
    ]


# ── Roles ─────────────────────────────────────────────────────────────────────

async def create_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: RoleCreate,
) -> RoleResponse:
    exists = (await db.execute(text("""
        SELECT id FROM iam.roles WHERE name = :name AND tenant_id = :tenant_id
    """), {"name": data.name, "tenant_id": str(tenant_id)})).scalar_one_or_none()
    if exists:
        raise ConflictError(f"Role '{data.name}' already exists")

    role_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO iam.roles (id, tenant_id, name, description, created_at, updated_at)
        VALUES (:id, :tenant_id, :name, :desc, now(), now())
    """), {"id": str(role_id), "tenant_id": str(tenant_id), "name": data.name, "desc": data.description})

    # Attach permissions
    for perm_id in data.permission_ids:
        await db.execute(text("""
            INSERT INTO iam.role_permissions (role_id, permission_id)
            VALUES (:role_id, :perm_id)
            ON CONFLICT DO NOTHING
        """), {"role_id": str(role_id), "perm_id": str(perm_id)})

    await db.commit()
    return await get_role(db, tenant_id, role_id)


async def get_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
) -> RoleResponse:
    row = (await db.execute(text("""
        SELECT r.*,
               COUNT(DISTINCT tm.user_id) AS user_count
        FROM iam.roles r
        LEFT JOIN iam.tenant_memberships tm
               ON tm.role_id = r.id AND tm.tenant_id = r.tenant_id
        WHERE r.id = :id AND r.tenant_id = :tenant_id
        GROUP BY r.id
    """), {"id": str(role_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"Role {role_id} not found")

    permissions = await _get_role_permissions(db, role_id)
    return RoleResponse(
        id=row["id"], tenant_id=row["tenant_id"], name=row["name"],
        description=row.get("description"), permissions=permissions,
        user_count=int(row.get("user_count", 0)),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


async def list_roles(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[RoleResponse]:
    rows = (await db.execute(text("""
        SELECT r.*,
               COUNT(DISTINCT tm.user_id) AS user_count
        FROM iam.roles r
        LEFT JOIN iam.tenant_memberships tm
               ON tm.role_id = r.id AND tm.tenant_id = r.tenant_id
        WHERE r.tenant_id = :tenant_id
        GROUP BY r.id
        ORDER BY r.name
    """), {"tenant_id": str(tenant_id)})).mappings().all()

    result = []
    for row in rows:
        permissions = await _get_role_permissions(db, uuid.UUID(str(row["id"])))
        result.append(RoleResponse(
            id=row["id"], tenant_id=row["tenant_id"], name=row["name"],
            description=row.get("description"), permissions=permissions,
            user_count=int(row.get("user_count", 0)),
            created_at=row["created_at"], updated_at=row["updated_at"],
        ))
    return result


async def update_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
    data: RoleUpdate,
) -> RoleResponse:
    await get_role(db, tenant_id, role_id)

    sets = ["updated_at = now()"]
    params: dict = {"id": str(role_id), "tenant_id": str(tenant_id)}

    if data.description is not None:
        sets.append("description = :desc"); params["desc"] = data.description

    await db.execute(text(f"""
        UPDATE iam.roles SET {', '.join(sets)}
        WHERE id = :id AND tenant_id = :tenant_id
    """), params)

    # Replace permission set if provided
    if data.permission_ids is not None:
        await db.execute(text("""
            DELETE FROM iam.role_permissions WHERE role_id = :role_id
        """), {"role_id": str(role_id)})
        for perm_id in data.permission_ids:
            await db.execute(text("""
                INSERT INTO iam.role_permissions (role_id, permission_id)
                VALUES (:role_id, :perm_id)
                ON CONFLICT DO NOTHING
            """), {"role_id": str(role_id), "perm_id": str(perm_id)})

    await db.commit()
    return await get_role(db, tenant_id, role_id)


async def delete_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
) -> None:
    await get_role(db, tenant_id, role_id)
    # Detach from memberships before deleting
    await db.execute(text("""
        UPDATE iam.tenant_memberships SET role_id = NULL WHERE role_id = :id
    """), {"id": str(role_id)})
    await db.execute(text("""
        DELETE FROM iam.role_permissions WHERE role_id = :id
    """), {"id": str(role_id)})
    await db.execute(text("""
        DELETE FROM iam.roles WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(role_id), "tenant_id": str(tenant_id)})
    await db.commit()


# ── Role assignment ───────────────────────────────────────────────────────────

async def assign_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> None:
    """Assign a custom role to a user within a tenant."""
    await db.execute(text("""
        INSERT INTO iam.tenant_memberships (user_id, tenant_id, role_id, joined_at)
        VALUES (:user_id, :tenant_id, :role_id, now())
        ON CONFLICT (user_id, tenant_id)
        DO UPDATE SET role_id = EXCLUDED.role_id
    """), {"user_id": str(user_id), "tenant_id": str(tenant_id), "role_id": str(role_id)})
    await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_role_permissions(db: AsyncSession, role_id: uuid.UUID) -> list[PermissionResponse]:
    rows = (await db.execute(text("""
        SELECT p.* FROM iam.permissions p
        JOIN iam.role_permissions rp ON rp.permission_id = p.id
        WHERE rp.role_id = :role_id
        ORDER BY p.name
    """), {"role_id": str(role_id)})).mappings().all()

    return [
        PermissionResponse(
            id=r["id"], name=r["name"], description=r.get("description"),
            resource=r["resource"], action=r["action"], created_at=r["created_at"],
        )
        for r in rows
    ]
