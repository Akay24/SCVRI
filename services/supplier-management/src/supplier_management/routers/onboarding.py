"""Onboarding router — state machine transition endpoint."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends

from supplier_management.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    require_write_access,
)
from supplier_management.schemas.supplier import (
    OnboardingTransitionRequest,
    SupplierResponse,
)
from supplier_management.services import supplier_service

router = APIRouter()


@router.post(
    "/{supplier_id}/onboarding/transition",
    response_model=SupplierResponse,
    summary="Transition a supplier through the onboarding state machine.",
    dependencies=[Depends(require_write_access)],
)
async def transition_onboarding(
    supplier_id: uuid.UUID,
    body: OnboardingTransitionRequest,
    db: TenantDB,
    tenant_id: TenantID,
    user_id: UserID,
):
    supplier = await supplier_service.transition_onboarding(
        db, tenant_id, supplier_id, user_id, body
    )
    await db.commit()
    await db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


@router.get(
    "/{supplier_id}/onboarding/status",
    summary="Get current onboarding status and allowed next transitions.",
)
async def get_onboarding_status(
    supplier_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    from supplier_management.services.supplier_service import (  # noqa: PLC0415
        _ONBOARDING_FSM,
        get_supplier,
    )
    supplier = await get_supplier(db, tenant_id, supplier_id)
    allowed_transitions = sorted(_ONBOARDING_FSM.get(supplier.onboarding_status, set()))
    return {
        "supplier_id": str(supplier.id),
        "current_status": supplier.onboarding_status,
        "allowed_transitions": allowed_transitions,
    }
