"""
SCIM 2.0 router — IdP user provisioning.

Base path: /scim/v2

Authentication: Bearer token (same JWT as API, must have it_administrator role).
Content-Type: application/scim+json (accepted for requests; returned in responses).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from iam.dependencies import AdminDep, TenantDbDep
from iam.schemas.user import SCIMListResponse, SCIMUserCreate, SCIMUserResponse
from iam.services import scim_service
from scvri_shared.exceptions import ConflictError, NotFoundError

SCIM_CONTENT_TYPE = "application/scim+json"

router = APIRouter(prefix="/scim/v2", tags=["scim"])


def _scim_response(data: dict, status_code: int = 200) -> Response:
    import json  # noqa: PLC0415
    return Response(
        content=json.dumps(data),
        status_code=status_code,
        media_type=SCIM_CONTENT_TYPE,
    )


@router.get("/ServiceProviderConfig", summary="SCIM service provider capabilities")
async def service_provider_config() -> dict:
    """Return SCIM ServiceProviderConfig indicating supported operations."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": True},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "name": "OAuth Bearer Token",
            "description": "Authentication using the OAuth Bearer Token Standard",
            "specUri": "http://www.rfc-editor.org/info/rfc6750",
            "type": "oauthbearertoken",
            "primary": True,
        }],
    }


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/Users", response_model=SCIMListResponse, summary="List SCIM users")
async def scim_list_users(
    db: TenantDbDep,
    claims: AdminDep,
    start_index: int = Query(1, alias="startIndex", ge=1),
    count: int = Query(100, alias="count", le=200),
    filter_str: Optional[str] = Query(None, alias="filter"),
) -> SCIMListResponse:
    return await scim_service.scim_list_users(
        db, claims.tenant_id, start_index, count, filter_str
    )


@router.post(
    "/Users",
    summary="Provision new user via SCIM",
    status_code=status.HTTP_201_CREATED,
)
async def scim_create_user(
    data: SCIMUserCreate,
    db: TenantDbDep,
    claims: AdminDep,
) -> SCIMUserResponse:
    try:
        return await scim_service.scim_create_user(db, claims.tenant_id, data)
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/Users/{user_id}", response_model=SCIMUserResponse, summary="Get SCIM user")
async def scim_get_user(
    user_id: str,
    db: TenantDbDep,
    claims: AdminDep,
) -> SCIMUserResponse:
    try:
        return await scim_service.scim_get_user(db, claims.tenant_id, user_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
                "status": "404",
                "detail": f"User {user_id} not found",
            },
        )


@router.put("/Users/{user_id}", response_model=SCIMUserResponse, summary="Replace SCIM user")
async def scim_replace_user(
    user_id: str,
    data: SCIMUserCreate,
    db: TenantDbDep,
    claims: AdminDep,
) -> SCIMUserResponse:
    try:
        return await scim_service.scim_replace_user(db, claims.tenant_id, user_id, data)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")


@router.patch("/Users/{user_id}", response_model=SCIMUserResponse, summary="Patch SCIM user")
async def scim_patch_user(
    user_id: str,
    request: Request,
    db: TenantDbDep,
    claims: AdminDep,
) -> SCIMUserResponse:
    body = await request.json()
    operations = body.get("Operations", [])
    try:
        return await scim_service.scim_patch_user(db, claims.tenant_id, user_id, operations)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deprovision SCIM user")
async def scim_delete_user(
    user_id: str,
    db: TenantDbDep,
    claims: AdminDep,
) -> None:
    try:
        await scim_service.scim_delete_user(db, claims.tenant_id, user_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")
