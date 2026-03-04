"""Rules router — CRUD and test-fire."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from alert_engine.dependencies import get_tenant_db, require_admin, require_write_access
from alert_engine.schemas.rule import AlertRuleCreate, AlertRuleResponse, AlertRuleUpdate
from alert_engine.services import rule_service
from scvri_shared.auth import TokenClaims

router = APIRouter(prefix="/rules", tags=["rules"])

DbDep = Annotated[AsyncSession, Depends(get_tenant_db)]
WriteDep = Annotated[TokenClaims, Depends(require_write_access)]
AdminDep = Annotated[TokenClaims, Depends(require_admin)]


@router.get("/", response_model=list[AlertRuleResponse])
async def list_rules(
    db: DbDep,
    claims: Annotated[TokenClaims, Depends()],
) -> list[AlertRuleResponse]:
    return await rule_service.list_rules(db, claims.tenant_id)


@router.post("/", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: AlertRuleCreate,
    db: DbDep,
    claims: AdminDep,
) -> AlertRuleResponse:
    """Create a new alert rule (admin only)."""
    return await rule_service.create_rule(db, claims.tenant_id, claims.user_id, data)


@router.get("/{rule_id}", response_model=AlertRuleResponse)
async def get_rule(
    rule_id: uuid.UUID,
    db: DbDep,
    claims: Annotated[TokenClaims, Depends()],
) -> AlertRuleResponse:
    return await rule_service.get_rule(db, claims.tenant_id, rule_id)


@router.patch("/{rule_id}", response_model=AlertRuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    data: AlertRuleUpdate,
    db: DbDep,
    claims: AdminDep,
) -> AlertRuleResponse:
    """Update an alert rule (admin only)."""
    return await rule_service.update_rule(db, claims.tenant_id, rule_id, data)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    db: DbDep,
    claims: AdminDep,
) -> None:
    """Soft-delete an alert rule (admin only)."""
    await rule_service.delete_rule(db, claims.tenant_id, rule_id)


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: uuid.UUID,
    sample_payload: dict[str, Any],
    db: DbDep,
    claims: AdminDep,
) -> dict[str, Any]:
    """
    Evaluate a rule against a sample event payload without firing alerts.
    Returns match result and which conditions passed or failed.
    """
    return await rule_service.test_rule(db, claims.tenant_id, rule_id, sample_payload)
