"""Model registry service — manage ML model versioning and promotion.

Champion lifecycle:
  staging → (evaluate) → champion (demotes old champion to archived)
                       → challenger (A/B test)
                       → archived
                       → failed
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import BusinessRuleError, NotFoundError
from scvri_shared.logging import get_logger
from scvri_shared.models.risk import MLModel
from risk_intelligence.ml.model_loader import evict_cache
from risk_intelligence.schemas.model import ModelArtifactUploadRequest, ModelResponse

log = get_logger(__name__)


async def register_model(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ModelArtifactUploadRequest,
) -> MLModel:
    """Register a new model version in staging state."""
    model = MLModel(
        id=uuid.uuid4(),
        name=data.name,
        version=data.version,
        framework=data.framework,
        description=data.description,
        feature_names=data.feature_names,
        hyperparameters=data.hyperparameters,
        metrics=data.metrics,
        artifact_path=data.artifact_path,
        status="staging",
        is_champion=False,
        created_by=user_id,
    )
    db.add(model)
    await db.flush()
    log.info("model.registered", model_id=str(model.id), version=data.version)
    return model


async def list_models(db: AsyncSession) -> list[MLModel]:
    result = await db.execute(
        select(MLModel)
        .where(MLModel.status != "archived")
        .order_by(MLModel.created_at.desc())
    )
    return list(result.scalars().all())


async def get_model(db: AsyncSession, model_id: uuid.UUID) -> MLModel:
    result = await db.execute(
        select(MLModel).where(MLModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise NotFoundError("model", str(model_id))
    return model


async def promote_to_champion(
    db: AsyncSession,
    model_id: uuid.UUID,
    promoted_by: uuid.UUID,
    reason: str,
) -> MLModel:
    """Promote a staging or challenger model to champion.

    Automatically demotes the current champion to archived.
    Evicts the model loader cache so the new model is loaded on next inference.
    """
    new_champion = await get_model(db, model_id)
    if new_champion.status not in {"staging", "challenger"}:
        raise BusinessRuleError(
            f"Only staging or challenger models can be promoted (current status: {new_champion.status})"
        )

    # Demote existing champion(s)
    await db.execute(
        update(MLModel)
        .where(MLModel.is_champion == True, MLModel.id != model_id)  # noqa: E712
        .values(is_champion=False, status="archived")
    )

    new_champion.status = "champion"
    new_champion.is_champion = True
    new_champion.promoted_at = datetime.now(tz=timezone.utc)

    # Clear the inference cache so new model loads on next request
    evict_cache()

    log.info(
        "model.promoted",
        model_id=str(model_id),
        version=new_champion.version,
        promoted_by=str(promoted_by),
        reason=reason,
    )
    return new_champion


async def archive_model(db: AsyncSession, model_id: uuid.UUID) -> MLModel:
    model = await get_model(db, model_id)
    if model.is_champion:
        raise BusinessRuleError("Cannot archive the champion model directly — promote another first.")
    model.status = "archived"
    model.is_champion = False
    evict_cache(model.artifact_path)
    return model


async def get_champion_model(db: AsyncSession) -> MLModel | None:
    result = await db.execute(
        select(MLModel).where(MLModel.is_champion == True).limit(1)  # noqa: E712
    )
    return result.scalar_one_or_none()
