"""Webhook registration management and inbound ingestion endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from integration.dependencies import AdminDep, DbDep, WebhookRLDep, WriteDep
from integration.schemas.webhook import WebhookDeliveryLog, WebhookRegistration
from integration.services.webhook_service import (
    WebhookNotFoundError,
    WebhookSignatureError,
    create_webhook_registration,
    delete_registration,
    get_registration,
    ingest_webhook,
    list_registrations,
)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ── Registration management (admin/write) ──────────────────────────────────────

@router.get("/registrations", summary="List inbound webhook registrations")
async def list_webhook_registrations(
    db: DbDep,
    claims: WriteDep,
) -> list[WebhookRegistration]:
    return await list_registrations(db, UUID(claims.tenant_id))


@router.post(
    "/registrations",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new inbound webhook",
)
async def create_registration(
    payload: WebhookRegistration,
    db: DbDep,
    claims: AdminDep,
) -> WebhookRegistration:
    if str(payload.tenant_id) != claims.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    return await create_webhook_registration(db, payload)


@router.get("/registrations/{registration_id}", summary="Get a webhook registration")
async def get_webhook_registration(
    registration_id: UUID,
    db: DbDep,
    claims: WriteDep,
) -> WebhookRegistration:
    reg = await get_registration(db, registration_id, UUID(claims.tenant_id))
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    return reg


@router.delete(
    "/registrations/{registration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a webhook registration",
)
async def delete_webhook_registration(
    registration_id: UUID,
    db: DbDep,
    claims: AdminDep,
) -> None:
    deleted = await delete_registration(db, registration_id, UUID(claims.tenant_id))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")


# ── Inbound webhook ingestion (public, HMAC-authenticated) ─────────────────────

@router.post(
    "/ingest/{registration_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive and process an inbound webhook",
    response_model=WebhookDeliveryLog,
    include_in_schema=True,
)
async def receive_webhook(
    registration_id: UUID,
    request: Request,
    db: DbDep,
    rate_limiter: WebhookRLDep,
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    x_webhook_event_id: str | None = Header(default=None, alias="X-Webhook-Event-ID"),
) -> WebhookDeliveryLog:
    body = await request.body()
    try:
        return await ingest_webhook(
            db,
            rate_limiter,
            registration_id,
            body=body,
            signature_header=x_webhook_signature,
            event_id=x_webhook_event_id,
        )
    except WebhookSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except WebhookNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
