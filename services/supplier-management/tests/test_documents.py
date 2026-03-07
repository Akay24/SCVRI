"""Tests for document upload flow — moto S3 + service layer mocks."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_TENANT_ID = uuid.uuid4()
_SUPPLIER_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_doc(**kwargs) -> MagicMock:
    d = MagicMock()
    d.id = kwargs.get("id", _DOC_ID)
    d.tenant_id = _TENANT_ID
    d.supplier_id = _SUPPLIER_ID
    d.document_type = "certificate"
    d.filename = "iso9001.pdf"
    d.content_type = "application/pdf"
    d.size_bytes = 1024 * 500  # 500 KB
    d.s3_key = f"{_TENANT_ID}/{_SUPPLIER_ID}/{_DOC_ID}/iso9001.pdf"
    d.s3_bucket = "test-supplier-docs"
    d.upload_status = kwargs.get("upload_status", "pending")
    d.checksum_sha256 = None
    d.confirmed_at = None
    d.uploaded_by = _USER_ID
    d.created_at = datetime.now(tz=timezone.utc)
    d.updated_at = None
    return d


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestDocumentSchemas:
    def test_size_limit_100mb(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from supplier_management.schemas.document import PresignedUploadRequest  # noqa: PLC0415

        with pytest.raises(ValidationError, match="size_bytes"):
            PresignedUploadRequest(
                filename="huge.zip",
                content_type="application/zip",
                size_bytes=101 * 1024 * 1024,  # > 100 MB ❌
                document_type="other",
            )

    def test_valid_request(self):
        from supplier_management.schemas.document import PresignedUploadRequest  # noqa: PLC0415

        req = PresignedUploadRequest(
            filename="contract.pdf",
            content_type="application/pdf",
            size_bytes=2 * 1024 * 1024,  # 2 MB
            document_type="contract",
        )
        assert req.filename == "contract.pdf"

    def test_confirm_request_checksum_length(self):
        from pydantic import ValidationError  # noqa: PLC0415
        from supplier_management.schemas.document import DocumentConfirmRequest  # noqa: PLC0415

        with pytest.raises(ValidationError, match="checksum_sha256"):
            DocumentConfirmRequest(
                document_id=_DOC_ID,
                checksum_sha256="tooshort",  # < 64 chars ❌
            )

    def test_confirm_request_valid(self):
        from supplier_management.schemas.document import DocumentConfirmRequest  # noqa: PLC0415

        valid_sha256 = "a" * 64
        req = DocumentConfirmRequest(document_id=_DOC_ID, checksum_sha256=valid_sha256)
        assert req.checksum_sha256 == valid_sha256


# ---------------------------------------------------------------------------
# Service layer — presigned URL generation
# ---------------------------------------------------------------------------
class TestDocumentService:
    @pytest.mark.asyncio
    async def test_generate_presigned_url_success(self):
        from supplier_management.services import document_service  # noqa: PLC0415
        from supplier_management.schemas.document import PresignedUploadRequest  # noqa: PLC0415

        req = PresignedUploadRequest(
            filename="cert.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            document_type="certificate",
        )

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_s3_response = {
            "url": "https://s3.example.com/upload",
            "fields": {"key": "test-key", "AWSAccessKeyId": "test"},
        }

        with patch(
            "supplier_management.services.document_service.get_supplier",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "supplier_management.services.document_service._s3_client"
        ) as mock_s3_cls:
            mock_s3_inst = MagicMock()
            mock_s3_inst.generate_presigned_post.return_value = mock_s3_response
            mock_s3_cls.return_value = mock_s3_inst

            result = await document_service.generate_presigned_upload_url(
                mock_db, _TENANT_ID, _SUPPLIER_ID, _USER_ID, req
            )

        assert result.upload_url == "https://s3.example.com/upload"
        assert result.document_id is not None
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirm_upload_not_found_raises(self):
        from scvri_shared.exceptions import NotFoundError  # noqa: PLC0415
        from supplier_management.services import document_service  # noqa: PLC0415
        from supplier_management.schemas.document import DocumentConfirmRequest  # noqa: PLC0415

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = DocumentConfirmRequest(
            document_id=uuid.uuid4(),
            checksum_sha256="b" * 64,
        )

        with pytest.raises(NotFoundError):
            await document_service.confirm_upload(
                mock_db, _TENANT_ID, _SUPPLIER_ID, req
            )

    @pytest.mark.asyncio
    async def test_confirm_upload_s3_object_missing_raises(self):
        from scvri_shared.exceptions import BusinessRuleError  # noqa: PLC0415
        from supplier_management.services import document_service  # noqa: PLC0415
        from supplier_management.schemas.document import DocumentConfirmRequest  # noqa: PLC0415
        from botocore.exceptions import ClientError  # noqa: PLC0415

        doc = _make_doc(upload_status="pending")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        req = DocumentConfirmRequest(
            document_id=doc.id,
            checksum_sha256="c" * 64,
        )

        client_error = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )

        with patch(
            "supplier_management.services.document_service._s3_client"
        ) as mock_s3_cls:
            mock_s3_inst = MagicMock()
            mock_s3_inst.head_object.side_effect = client_error
            mock_s3_cls.return_value = mock_s3_inst

            with pytest.raises(BusinessRuleError, match="not found in S3"):
                await document_service.confirm_upload(
                    mock_db, _TENANT_ID, _SUPPLIER_ID, req
                )

    @pytest.mark.asyncio
    async def test_download_url_requires_clean_status(self):
        from scvri_shared.exceptions import BusinessRuleError  # noqa: PLC0415
        from supplier_management.services import document_service  # noqa: PLC0415

        doc = _make_doc(upload_status="scanning")  # not clean

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(BusinessRuleError, match="not yet clean"):
            await document_service.get_document_download_url(
                mock_db, _TENANT_ID, _SUPPLIER_ID, doc.id
            )


# ---------------------------------------------------------------------------
# Moto S3 integration (requires moto[s3] + boto3)
# ---------------------------------------------------------------------------
class TestDocumentServiceWithMoto:
    """Integration-style tests using moto's in-memory S3."""

    @pytest.mark.asyncio
    async def test_confirm_upload_sets_scanning_status(self):
        pytest.importorskip("moto")
        import boto3  # noqa: PLC0415
        from moto import mock_aws  # noqa: PLC0415
        from supplier_management.services import document_service  # noqa: PLC0415
        from supplier_management.schemas.document import DocumentConfirmRequest  # noqa: PLC0415

        bucket = "test-supplier-docs"
        key = f"{_TENANT_ID}/{_SUPPLIER_ID}/{_DOC_ID}/iso9001.pdf"

        doc = _make_doc()
        doc.s3_bucket = bucket
        doc.s3_key = key
        doc.upload_status = "pending"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=bucket)
            s3.put_object(Bucket=bucket, Key=key, Body=b"fake-pdf-content")

            req = DocumentConfirmRequest(
                document_id=doc.id,
                checksum_sha256="d" * 64,
            )

            with patch(
                "supplier_management.services.document_service._enqueue_scan"
            ) as mock_enqueue:
                result = await document_service.confirm_upload(
                    mock_db, _TENANT_ID, _SUPPLIER_ID, req
                )

        assert result.upload_status == "scanning"
        mock_enqueue.assert_called_once_with(str(doc.id), str(_TENANT_ID))
