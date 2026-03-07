"""Pydantic schemas for supplier documents (S3 doc vault)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from scvri_shared.schemas import CamelBase, TimestampSchema

VALID_DOC_TYPES = {"certification", "financial_statement", "insurance", "questionnaire", "contract", "other"}


class DocumentUploadResponse(TimestampSchema):
    """Returned immediately after the presigned-URL upload is confirmed."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    document_type: str
    upload_status: str            # pending → scanning → clean / infected / failed
    s3_key: str                   # shown only to admin roles
    checksum_sha256: str | None


class DocumentResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    document_type: str
    upload_status: str
    uploaded_by: uuid.UUID | None
    checksum_sha256: str | None


class PresignedUploadRequest(CamelBase):
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=1, le=104_857_600)   # 100 MB hard cap
    document_type: str = Field(default="other")

    @classmethod
    def validate_doc_type(cls, v: str) -> str:
        if v not in VALID_DOC_TYPES:
            raise ValueError(f"document_type must be one of {VALID_DOC_TYPES}")
        return v


class PresignedUploadResponse(CamelBase):
    upload_url: str             # PUT to this URL (expires 15 min)
    document_id: uuid.UUID      # use this to confirm upload
    fields: dict                # any extra form fields (for POST multipart)
    expires_at: datetime


class DocumentConfirmRequest(CamelBase):
    document_id: uuid.UUID
    checksum_sha256: str = Field(min_length=64, max_length=64)
