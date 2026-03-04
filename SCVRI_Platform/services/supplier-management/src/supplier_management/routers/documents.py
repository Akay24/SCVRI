"""Documents router — presigned upload, confirm, download, list, delete."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from scvri_shared.schemas import OperationResult
from supplier_management.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    require_write_access,
)
from supplier_management.schemas.document import (
    DocumentConfirmRequest,
    DocumentResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
)
from supplier_management.services import document_service

router = APIRouter()


@router.post(
    "/{supplier_id}/documents/presigned",
    response_model=PresignedUploadResponse,
    status_code=201,
    summary="Generate a presigned S3 upload URL.",
    dependencies=[Depends(require_write_access)],
)
async def generate_presigned_url(
    supplier_id: uuid.UUID,
    body: PresignedUploadRequest,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    result = await document_service.generate_presigned_upload_url(
        db, tenant_id, supplier_id, user_id, body
    )
    await db.commit()
    return result


@router.post(
    "/{supplier_id}/documents/{document_id}/confirm",
    response_model=DocumentResponse,
    summary="Confirm upload completion and trigger virus scan.",
    dependencies=[Depends(require_write_access)],
)
async def confirm_upload(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentConfirmRequest,
    db: TenantDB,
    tenant_id: TenantID,
):
    body.document_id = document_id  # inject path param
    doc = await document_service.confirm_upload(db, tenant_id, supplier_id, body)
    await db.commit()
    await db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.get(
    "/{supplier_id}/documents",
    response_model=list[DocumentResponse],
    summary="List all documents for a supplier.",
)
async def list_documents(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    docs = await document_service.list_documents(db, tenant_id, supplier_id)
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get(
    "/{supplier_id}/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata.",
)
async def get_document(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    doc = await document_service.get_document(db, tenant_id, supplier_id, document_id)
    return DocumentResponse.model_validate(doc)


@router.get(
    "/{supplier_id}/documents/{document_id}/download-url",
    summary="Get a presigned download URL for a clean document.",
)
async def get_download_url(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    url = await document_service.get_document_download_url(
        db, tenant_id, supplier_id, document_id
    )
    return {"download_url": url}


@router.delete(
    "/{supplier_id}/documents/{document_id}",
    status_code=204,
    dependencies=[Depends(require_write_access)],
)
async def delete_document(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    await document_service.delete_document(db, tenant_id, supplier_id, document_id)
    await db.commit()
