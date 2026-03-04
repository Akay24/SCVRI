"""Model registry router — register, list, promote, archive ML models."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from risk_intelligence.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    require_ml_admin,
)
from risk_intelligence.schemas.model import (
    ModelArtifactUploadRequest,
    ModelPredictRequest,
    ModelPredictResponse,
    ModelPromoteRequest,
    ModelResponse,
)
from risk_intelligence.services import model_registry_service

router = APIRouter(prefix="/models", tags=["Model Registry"])


@router.get("/", response_model=list[ModelResponse])
async def list_models(
    db: TenantDB,
    tenant_id: TenantID,
):
    models = await model_registry_service.list_models(db)
    return [ModelResponse.model_validate(m) for m in models]


@router.post(
    "/",
    response_model=ModelResponse,
    status_code=201,
    dependencies=[Depends(require_ml_admin)],
    summary="Register a new model artifact (S3 path must exist in ml-artifacts bucket).",
)
async def register_model(
    body: ModelArtifactUploadRequest,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    model = await model_registry_service.register_model(db, tenant_id, user_id, body)
    await db.commit()
    await db.refresh(model)
    return ModelResponse.model_validate(model)


@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    model = await model_registry_service.get_model(db, model_id)
    return ModelResponse.model_validate(model)


@router.post(
    "/promote",
    response_model=ModelResponse,
    dependencies=[Depends(require_ml_admin)],
    summary="Promote a model to champion (demotes current champion to archived).",
)
async def promote_model(
    body: ModelPromoteRequest,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    model = await model_registry_service.promote_to_champion(
        db, body.model_id, user_id, body.reason
    )
    await db.commit()
    await db.refresh(model)
    return ModelResponse.model_validate(model)


@router.delete(
    "/{model_id}",
    status_code=204,
    dependencies=[Depends(require_ml_admin)],
    summary="Archive (soft-delete) a non-champion model.",
)
async def archive_model(
    model_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    await model_registry_service.archive_model(db, model_id)
    await db.commit()
    return Response(status_code=204)
