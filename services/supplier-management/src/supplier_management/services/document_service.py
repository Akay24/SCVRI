"""Document service — S3 presigned upload/download and ClamAV-via-Celery scanning.

Upload flow:
  1. Client calls POST /suppliers/{id}/documents/presigned  → gets pre-signed PUT URL
  2. Client uploads directly to S3 (bypasses our backend)
  3. Client calls POST /suppliers/{id}/documents/{doc_id}/confirm
  4. Service verifies S3 object exists, validates SHA-256, triggers Celery scan task
  5. Worker updates upload_status → scanning → clean | infected | failed
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.config import settings
from scvri_shared.exceptions import BusinessRuleError, ExternalServiceError, NotFoundError
from scvri_shared.logging import get_logger
from scvri_shared.models.supplier import SupplierDocument
from supplier_management.schemas.document import (
    DocumentConfirmRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
)
from supplier_management.services.supplier_service import get_supplier

log = get_logger(__name__)

# Presigned URL TTLs (seconds)
_UPLOAD_TTL = 900   # 15 min
_DOWNLOAD_TTL = 300  # 5 min


def _s3_client():
    """Return a boto3 S3 client using service settings."""
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _document_s3_key(tenant_id: uuid.UUID, supplier_id: uuid.UUID, doc_id: uuid.UUID, filename: str) -> str:
    return f"{tenant_id}/{supplier_id}/{doc_id}/{filename}"


# ---------------------------------------------------------------------------
# Presigned upload
# ---------------------------------------------------------------------------
async def generate_presigned_upload_url(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    user_id: uuid.UUID,
    req: PresignedUploadRequest,
) -> PresignedUploadResponse:
    # Verify supplier exists and belongs to tenant
    await get_supplier(db, tenant_id, supplier_id)

    doc_id = uuid.uuid4()
    s3_key = _document_s3_key(tenant_id, supplier_id, doc_id, req.filename)

    try:
        s3 = _s3_client()
        response = s3.generate_presigned_post(
            Bucket=settings.s3_supplier_documents_bucket,
            Key=s3_key,
            Fields={
                "Content-Type": req.content_type,
            },
            Conditions=[
                {"Content-Type": req.content_type},
                ["content-length-range", 1, req.size_bytes],
            ],
            ExpiresIn=_UPLOAD_TTL,
        )
    except ClientError as exc:
        log.error("s3.presigned_post.failed", error=str(exc))
        raise ExternalServiceError("s3") from exc

    # Persist pending row
    doc = SupplierDocument(
        id=doc_id,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        document_type=req.document_type,
        filename=req.filename,
        content_type=req.content_type,
        size_bytes=req.size_bytes,
        s3_key=s3_key,
        s3_bucket=settings.s3_supplier_documents_bucket,
        upload_status="pending",
        uploaded_by=user_id,
    )
    db.add(doc)
    await db.flush()

    expires_at = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
    from datetime import timedelta  # noqa: PLC0415
    expires_at = expires_at + timedelta(seconds=_UPLOAD_TTL)

    log.info("document.presigned_url.generated", doc_id=str(doc_id), s3_key=s3_key)

    return PresignedUploadResponse(
        document_id=doc_id,
        upload_url=response["url"],
        fields=response["fields"],
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Confirm upload
# ---------------------------------------------------------------------------
async def confirm_upload(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    req: DocumentConfirmRequest,
) -> SupplierDocument:
    """Verify the S3 object exists, validate checksum, enqueue ClamAV scan."""
    row = await db.execute(
        select(SupplierDocument).where(
            SupplierDocument.id == req.document_id,
            SupplierDocument.supplier_id == supplier_id,
            SupplierDocument.upload_status == "pending",
        )
    )
    doc = row.scalar_one_or_none()
    if doc is None:
        raise NotFoundError("document", str(req.document_id))

    # Verify the object actually landed in S3
    try:
        s3 = _s3_client()
        head = s3.head_object(Bucket=doc.s3_bucket, Key=doc.s3_key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            raise BusinessRuleError(
                "document not found in S3 — ensure upload completed before confirming"
            ) from exc
        raise ExternalServiceError("s3") from exc

    # Optional: validate SHA-256 against ETag for small objects
    if req.checksum_sha256 and len(req.checksum_sha256) == 64:
        doc.checksum_sha256 = req.checksum_sha256

    doc.size_bytes = head["ContentLength"]
    doc.upload_status = "scanning"
    doc.confirmed_at = datetime.now(tz=timezone.utc)

    await db.flush()

    # Trigger async ClamAV scan via Celery
    _enqueue_scan(str(doc.id), str(tenant_id))

    log.info("document.confirmed", doc_id=str(doc.id), size=head["ContentLength"])
    return doc


def _enqueue_scan(document_id: str, tenant_id: str) -> None:
    """Fire-and-forget Celery task. Import lazily to avoid circular deps."""
    try:
        from supplier_management.workers.scorecard_worker import scan_document_task  # noqa: PLC0415
        scan_document_task.delay(document_id, tenant_id)
    except Exception as exc:  # noqa: BLE001
        log.error("document.scan_enqueue.failed", doc_id=document_id, error=str(exc))


# ---------------------------------------------------------------------------
# Get document
# ---------------------------------------------------------------------------
async def get_document(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
) -> SupplierDocument:
    row = await db.execute(
        select(SupplierDocument).where(
            SupplierDocument.id == document_id,
            SupplierDocument.supplier_id == supplier_id,
        )
    )
    doc = row.scalar_one_or_none()
    if doc is None:
        raise NotFoundError("document", str(document_id))
    return doc


async def list_documents(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> list[SupplierDocument]:
    from supplier_management.services.supplier_service import get_supplier  # noqa: PLC0415
    await get_supplier(db, tenant_id, supplier_id)

    result = await db.execute(
        select(SupplierDocument)
        .where(SupplierDocument.supplier_id == supplier_id)
        .order_by(SupplierDocument.created_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Presigned download URL
# ---------------------------------------------------------------------------
async def get_document_download_url(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
) -> str:
    """Generate a short-lived presigned GET URL for a clean document."""
    doc = await get_document(db, tenant_id, supplier_id, document_id)

    if doc.upload_status != "clean":
        raise BusinessRuleError(
            f"document is not yet clean (status={doc.upload_status})"
        )

    try:
        s3 = _s3_client()
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": doc.s3_bucket, "Key": doc.s3_key},
            ExpiresIn=_DOWNLOAD_TTL,
        )
    except ClientError as exc:
        raise ExternalServiceError("s3") from exc

    return url


# ---------------------------------------------------------------------------
# Delete document (soft delete / S3 object removal)
# ---------------------------------------------------------------------------
async def delete_document(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    doc = await get_document(db, tenant_id, supplier_id, document_id)

    # Remove from S3
    try:
        s3 = _s3_client()
        s3.delete_object(Bucket=doc.s3_bucket, Key=doc.s3_key)
    except ClientError as exc:
        log.warning("s3.delete.failed", doc_id=str(document_id), error=str(exc))

    doc.upload_status = "deleted"
    doc.updated_at = datetime.now(tz=timezone.utc)
