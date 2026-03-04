"""Telemetry & devices router."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from visibility.dependencies import TenantDB, TenantID, require_write_access
from visibility.schemas.telemetry import (
    DeviceCreate,
    DeviceResponse,
    GeofenceCreate,
    GeofenceResponse,
    TelemetryEventResponse,
    TelemetryPayload,
    TelemetryQueryParams,
)
from visibility.services import telemetry_service

router = APIRouter(tags=["Telemetry & IoT"])


# ── Telemetry ingest ──────────────────────────────────────────────────────────

@router.post(
    "/telemetry",
    response_model=TelemetryEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_telemetry(
    db: TenantDB,
    tenant_id: TenantID,
    body: TelemetryPayload,
):
    """Ingest a single telemetry event from an IoT device (REST path)."""
    return await telemetry_service.process_telemetry(db, tenant_id, body)


@router.get("/telemetry", response_model=list[TelemetryEventResponse])
async def query_telemetry(
    db: TenantDB,
    tenant_id: TenantID,
    shipment_id: Annotated[uuid.UUID | None, Query()] = None,
    device_id: Annotated[str | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
    from_dt: Annotated[datetime | None, Query()] = None,
    to_dt: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    params = TelemetryQueryParams(
        shipment_id=shipment_id,
        device_id=device_id,
        event_type=event_type,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
    )
    return await telemetry_service.query_telemetry(db, tenant_id, params)


# ── Geofences ─────────────────────────────────────────────────────────────────

@router.get("/geofences", response_model=list[GeofenceResponse])
async def list_geofences(
    db: TenantDB,
    tenant_id: TenantID,
):
    return await telemetry_service.list_geofences(db, tenant_id)


@router.post(
    "/geofences",
    response_model=GeofenceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
async def create_geofence(
    db: TenantDB,
    tenant_id: TenantID,
    body: GeofenceCreate,
):
    return await telemetry_service.create_geofence(db, tenant_id, body)


@router.get("/geofences/{geo_id}", response_model=GeofenceResponse)
async def get_geofence(
    geo_id: uuid.UUID,
    db: TenantDB,
    tenant_id: TenantID,
):
    return await telemetry_service.get_geofence(db, tenant_id, geo_id)


# ── Devices ───────────────────────────────────────────────────────────────────

@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
)
async def register_device(
    db: TenantDB,
    tenant_id: TenantID,
    body: DeviceCreate,
):
    return await telemetry_service.register_device(db, tenant_id, body)
