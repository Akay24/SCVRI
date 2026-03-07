"""Rules router — CRUD and test-fire."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from alert_engine.dependencies import (
    TenantDB,
    TenantID,
    UserID,
    get_tenant_db,
    require_admin,
    require_write_access,
)
from alert_engine.schemas.rule import AlertRuleCreate, AlertRuleResponse, AlertRuleUpdate
from alert_engine.services import rule_service

router = APIRouter(prefix="/rules", tags=["rules"])

DbDep = TenantDB
WriteDep = Annotated[None, Depends(require_write_access)]
AdminDep = Annotated[None, Depends(require_admin)]


@router.get("/", response_model=list[AlertRuleResponse])
async def list_rules(
    db: DbDep,
    tenant_id: TenantID,
) -> list[AlertRuleResponse]:
    return await rule_service.list_rules(db, tenant_id)


@router.post("/", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    data: AlertRuleCreate,
    db: DbDep,
    tenant_id: TenantID,
    user_id: UserID,
    _: AdminDep,
) -> AlertRuleResponse:
    """Create a new alert rule (admin only)."""
    return await rule_service.create_rule(db, tenant_id, user_id, data)


@router.get("/{rule_id}", response_model=AlertRuleResponse)
async def get_rule(
    rule_id: uuid.UUID,
    db: DbDep,
    tenant_id: TenantID,
) -> AlertRuleResponse:
    return await rule_service.get_rule(db, tenant_id, rule_id)


@router.patch("/{rule_id}", response_model=AlertRuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    data: AlertRuleUpdate,
    db: DbDep,
    tenant_id: TenantID,
    _: AdminDep,
) -> AlertRuleResponse:
    """Update an alert rule (admin only)."""
    return await rule_service.update_rule(db, tenant_id, rule_id, data)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    db: DbDep,
    tenant_id: TenantID,
    _: AdminDep,
) -> None:
    """Soft-delete an alert rule (admin only)."""
    await rule_service.delete_rule(db, tenant_id, rule_id)


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: uuid.UUID,
    sample_payload: dict[str, Any],
    db: DbDep,
    tenant_id: TenantID,
    _: AdminDep,
) -> dict[str, Any]:
    """
    Evaluate a rule against a sample event payload without firing alerts.
    Returns match result and which conditions passed or failed.
    """
    return await rule_service.test_rule(db, tenant_id, rule_id, sample_payload)
