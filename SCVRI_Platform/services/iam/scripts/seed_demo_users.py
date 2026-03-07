#!/usr/bin/env python3
"""
Seed demo users into the IAM database.

Requires the IAM service dependencies to be installed and environment variables set.
Run from the services/iam directory:

    python scripts/seed_demo_users.py

Environment variables needed (same as the IAM service):
    SCVRI_DB_URL   — PostgreSQL connection string (public schema)
    SCVRI_TENANT_ID — (optional) UUID for the demo tenant; defaults to a fixed dev UUID
"""
from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

TENANT_ID = uuid.UUID(os.environ.get("SCVRI_TENANT_ID", "00000000-0000-0000-0000-000000000001"))
DB_URL    = os.environ.get("SCVRI_DB_URL", "postgresql://postgres:postgres@localhost:5432/scvri")

# ---------------------------------------------------------------------------
# Demo users — one per platform role
# ---------------------------------------------------------------------------
DEMO_USERS = [
    {
        "email":     "admin@scvri.dev",
        "full_name": "Alex Admin",
        "password":  "Admin1234!",
        "role":      "it_administrator",
        "description": "Full platform access — Admin panel, all CRUD",
    },
    {
        "email":     "manager@scvri.dev",
        "full_name": "Sam Manager",
        "password":  "Manager1!",
        "role":      "supply_chain_manager",
        "description": "Suppliers, Shipments, Alerts, Reports",
    },
    {
        "email":     "procurement@scvri.dev",
        "full_name": "Pat Procurement",
        "password":  "Procure1!",
        "role":      "procurement_officer",
        "description": "Suppliers, Shipments read + write",
    },
    {
        "email":     "analyst@scvri.dev",
        "full_name": "Riley Analyst",
        "password":  "Analyst1!",
        "role":      "risk_analyst",
        "description": "Risk Intelligence, Alerts, read-only Suppliers",
    },
    {
        "email":     "viewer@scvri.dev",
        "full_name": "Val Viewer",
        "password":  "Viewer12!",
        "role":      "viewer",
        "description": "Dashboard and Supply Chain Map only",
    },
]


async def seed() -> None:
    conn = await asyncpg.connect(DB_URL)
    try:
        # Ensure demo tenant exists
        await conn.execute("""
            INSERT INTO public.tenants (id, name, domain, status)
            VALUES ($1, 'SCVRI Demo Tenant', 'scvri.dev', 'active')
            ON CONFLICT (id) DO NOTHING
        """, TENANT_ID)

        for u in DEMO_USERS:
            uid   = uuid.uuid4()
            phash = _pwd.hash(u["password"])
            await conn.execute("""
                INSERT INTO iam.users
                    (id, tenant_id, email, full_name, password_hash, role, status,
                     mfa_enabled, created_at, updated_at)
                VALUES
                    ($1, $2, $3, $4, $5, $6, 'active',
                     false, now(), now())
                ON CONFLICT (email, tenant_id) DO UPDATE
                    SET full_name = EXCLUDED.full_name,
                        password_hash = EXCLUDED.password_hash,
                        role = EXCLUDED.role,
                        updated_at = now()
            """, uid, TENANT_ID, u["email"], u["full_name"], phash, u["role"])

            print(f"  ✓  {u['email']:35s}  role={u['role']:25s}  [{u['description']}]")

        print("\nDone — demo tenant:", TENANT_ID)
    finally:
        await conn.close()


if __name__ == "__main__":
    print(f"\nSeeding demo users into {DB_URL!r} (tenant {TENANT_ID})\n")
    asyncio.run(seed())
