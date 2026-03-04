"""
SCIM 2.0 user provisioning service (RFC 7643 / 7644).

Supports:
  - GET    /scim/v2/Users            — list users
  - GET    /scim/v2/Users/{id}       — get user
  - POST   /scim/v2/Users            — create user (provisioning from IdP)
  - PUT    /scim/v2/Users/{id}       — replace user
  - PATCH  /scim/v2/Users/{id}       — partial update (active flag for deprovisioning)
  - DELETE /scim/v2/Users/{id}       — deprovision (soft-delete)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from iam.core.security import hash_password, generate_totp_secret
from iam.schemas.user import (
    SCIMEmail,
    SCIMListResponse,
    SCIMUserCreate,
    SCIMUserName,
    SCIMUserResponse,
)
from scvri_shared.exceptions import ConflictError, NotFoundError
from scvri_shared.logging import get_logger

log = get_logger(__name__)

SCIM_SCHEMAS = ["urn:ietf:params:scim:schemas:core:2.0:User"]


def _scim_meta(user_id: str, tenant_id: str, created_at: datetime, updated_at: datetime) -> dict:
    return {
        "resourceType": "User",
        "created": created_at.isoformat(),
        "lastModified": updated_at.isoformat(),
        "location": f"/scim/v2/Users/{user_id}",
        "version": f'W/"{updated_at.timestamp()}"',
    }


# ── List ──────────────────────────────────────────────────────────────────────

async def scim_list_users(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start_index: int = 1,
    count: int = 100,
    filter_str: str | None = None,
) -> SCIMListResponse:
    offset = max(0, start_index - 1)
    params: dict = {"tenant_id": str(tenant_id), "limit": count, "offset": offset}
    extra_where = ""

    # Basic SCIM filter — support "userName eq value" only
    if filter_str:
        filter_str = filter_str.strip()
        if filter_str.lower().startswith("username eq "):
            email_val = filter_str[len("userName eq "):].strip().strip('"')
            extra_where = "AND email = :filter_email"
            params["filter_email"] = email_val.lower()

    rows = (await db.execute(text(f"""
        SELECT * FROM iam.users
        WHERE tenant_id = :tenant_id AND status != 'inactive'
        {extra_where}
        ORDER BY full_name
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()

    total = (await db.execute(text(f"""
        SELECT COUNT(*) FROM iam.users
        WHERE tenant_id = :tenant_id AND status != 'inactive' {extra_where}
    """), params)).scalar_one()

    resources = [_row_to_scim(r) for r in rows]
    return SCIMListResponse(
        total_results=int(total),
        start_index=start_index,
        items_per_page=count,
        resources=resources,
    )


# ── Get ───────────────────────────────────────────────────────────────────────

async def scim_get_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scim_user_id: str,
) -> SCIMUserResponse:
    row = (await db.execute(text("""
        SELECT * FROM iam.users WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": scim_user_id, "tenant_id": str(tenant_id)})).mappings().one_or_none()
    if row is None:
        raise NotFoundError(f"SCIM User {scim_user_id} not found")
    return _row_to_scim(row)


# ── Create ────────────────────────────────────────────────────────────────────

async def scim_create_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: SCIMUserCreate,
) -> SCIMUserResponse:
    email = data.user_name.lower()

    # Check uniqueness
    existing = (await db.execute(text("""
        SELECT id FROM iam.users WHERE email = :email AND tenant_id = :tenant_id
    """), {"email": email, "tenant_id": str(tenant_id)})).scalar_one_or_none()
    if existing:
        raise ConflictError(f"User with email '{email}' already exists")

    user_id = uuid.uuid4()

    # Build full_name from SCIM name object
    full_name = _extract_full_name(data)

    # Temporary random password (user must reset via forgot-password flow)
    tmp_pw = hash_password(str(uuid.uuid4()))

    await db.execute(text("""
        INSERT INTO iam.users
            (id, tenant_id, email, full_name, password_hash, role, status,
             mfa_enabled, mfa_method, external_id, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :email, :full_name, :pw, 'viewer',
             CASE WHEN :active THEN 'active' ELSE 'inactive' END,
             FALSE, 'none', :external_id, now(), now())
    """), {
        "id": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "full_name": full_name,
        "pw": tmp_pw,
        "active": data.active,
        "external_id": data.external_id,
    })
    await db.commit()

    log.info("scim.user.created", user_id=str(user_id), tenant_id=str(tenant_id))
    return await scim_get_user(db, tenant_id, str(user_id))


# ── Replace (PUT) ─────────────────────────────────────────────────────────────

async def scim_replace_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scim_user_id: str,
    data: SCIMUserCreate,
) -> SCIMUserResponse:
    await scim_get_user(db, tenant_id, scim_user_id)  # 404 guard

    full_name = _extract_full_name(data)
    status_val = "active" if data.active else "inactive"

    await db.execute(text("""
        UPDATE iam.users
        SET full_name = :full_name,
            status = :status,
            external_id = :external_id,
            updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {
        "full_name": full_name,
        "status": status_val,
        "external_id": data.external_id,
        "id": scim_user_id,
        "tenant_id": str(tenant_id),
    })
    await db.commit()
    return await scim_get_user(db, tenant_id, scim_user_id)


# ── Patch ─────────────────────────────────────────────────────────────────────

async def scim_patch_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scim_user_id: str,
    operations: list[dict],
) -> SCIMUserResponse:
    """
    Apply SCIM PATCH operations.
    Only supports `op=replace` on `active` attribute for deprovisioning.
    """
    await scim_get_user(db, tenant_id, scim_user_id)

    for op in operations:
        op_type = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if op_type == "replace":
            if path == "active" or (isinstance(value, dict) and "active" in value):
                active_val = value if isinstance(value, bool) else (value or {}).get("active", True)
                new_status = "active" if active_val else "inactive"
                await db.execute(text("""
                    UPDATE iam.users SET status = :status, updated_at = now()
                    WHERE id = :id AND tenant_id = :tenant_id
                """), {"status": new_status, "id": scim_user_id, "tenant_id": str(tenant_id)})

    await db.commit()
    return await scim_get_user(db, tenant_id, scim_user_id)


# ── Delete ────────────────────────────────────────────────────────────────────

async def scim_delete_user(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    scim_user_id: str,
) -> None:
    await scim_get_user(db, tenant_id, scim_user_id)
    await db.execute(text("""
        UPDATE iam.users SET status = 'inactive', updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": scim_user_id, "tenant_id": str(tenant_id)})
    await db.commit()
    log.info("scim.user.deprovisioned", scim_user_id=scim_user_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_full_name(data: SCIMUserCreate) -> str:
    if data.name:
        if data.name.formatted:
            return data.name.formatted
        parts = [data.name.given_name, data.name.family_name]
        joined = " ".join(p for p in parts if p)
        if joined:
            return joined
    # Fall back to email username part
    email = data.user_name
    return email.split("@")[0].replace(".", " ").title()


def _row_to_scim(row: dict) -> SCIMUserResponse:
    email = row["email"]
    full_name = row["full_name"]
    name_parts = full_name.split(" ", 1)
    given = name_parts[0] if name_parts else ""
    family = name_parts[1] if len(name_parts) > 1 else ""

    return SCIMUserResponse(
        schemas=SCIM_SCHEMAS,
        id=str(row["id"]),
        external_id=row.get("external_id"),
        user_name=email,
        name=SCIMUserName(formatted=full_name, given_name=given, family_name=family),
        emails=[SCIMEmail(value=email, primary=True, type="work")],
        active=row["status"] == "active",
        meta=_scim_meta(
            str(row["id"]),
            str(row["tenant_id"]),
            row["created_at"],
            row["updated_at"],
        ),
    )
