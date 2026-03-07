"""Contacts router — CRUD for supplier contacts."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, Response

from supplier_management.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    require_write_access,
)
from supplier_management.schemas.supplier import (
    ContactCreate,
    ContactResponse,
    ContactUpdate,
)
from supplier_management.services import supplier_service

router = APIRouter()


@router.get("/{supplier_id}/contacts", response_model=list[ContactResponse])
async def list_contacts(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    contacts = await supplier_service.list_contacts(db, tenant_id, supplier_id)
    return [ContactResponse.model_validate(c) for c in contacts]


@router.post(
    "/{supplier_id}/contacts",
    response_model=ContactResponse,
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
async def create_contact(
    supplier_id: uuid.UUID,
    body: ContactCreate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    contact = await supplier_service.create_contact(db, tenant_id, supplier_id, body)
    await db.commit()
    await db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.put(
    "/{supplier_id}/contacts/{contact_id}",
    response_model=ContactResponse,
    dependencies=[Depends(require_write_access)],
)
async def update_contact(
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: ContactUpdate,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    contact = await supplier_service.update_contact(
        db, tenant_id, supplier_id, contact_id, body
    )
    await db.commit()
    await db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.delete(
    "/{supplier_id}/contacts/{contact_id}",
    status_code=204,
    dependencies=[Depends(require_write_access)],
)
async def delete_contact(
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    await supplier_service.delete_contact(db, tenant_id, supplier_id, contact_id)
    await db.commit()
    return Response(status_code=204)
