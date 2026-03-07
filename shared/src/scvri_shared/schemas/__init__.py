"""Pydantic v2 base schemas shared across all SCVRI services.

Each service defines its own request/response schemas but imports from here:
  - CamelBase — all schemas use camelCase JSON keys
  - PaginatedResponse[T] — standard list wrapper
  - ErrorResponse — RFC 7807 Problem Details
  - Common field types: TenantId, UserId, SupplierId, etc.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Shared field types
# ---------------------------------------------------------------------------
TenantId = Annotated[uuid.UUID, Field(description="Tenant UUID")]
UserId = Annotated[uuid.UUID, Field(description="User UUID")]
SupplierId = Annotated[uuid.UUID, Field(description="Supplier UUID")]
POId = Annotated[uuid.UUID, Field(description="Purchase Order UUID")]
ShipmentId = Annotated[uuid.UUID, Field(description="Shipment UUID")]
AlertId = Annotated[uuid.UUID, Field(description="Alert UUID")]
RiskScoreId = Annotated[uuid.UUID, Field(description="Risk Score UUID")]

T = TypeVar("T")


# ---------------------------------------------------------------------------
# CamelBase — all schemas use camelCase JSON serialisation
# ---------------------------------------------------------------------------
def _to_camel(name: str) -> str:
    components = name.split("_")
    return components[0] + "".join(word.capitalize() for word in components[1:])


class CamelBase(BaseModel):
    """Base model: camelCase alias generation + ORM mode + strict datetime serialisation."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,      # accept both snake_case and camelCase on input
        from_attributes=True,       # ORM mode
        ser_json_timedelta="iso8601",
    )


# ---------------------------------------------------------------------------
# Timestamp mixin for response schemas
# ---------------------------------------------------------------------------
class TimestampSchema(CamelBase):
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
class PaginationMeta(CamelBase):
    page: int = Field(ge=1, default=1, description="Current page number (1-based)")
    page_size: int = Field(ge=1, le=200, default=20, description="Items per page")
    total_items: int = Field(ge=0, description="Total matching items across all pages")
    total_pages: int = Field(ge=0, description="Total number of pages")

    @model_validator(mode="after")
    def compute_total_pages(self) -> "PaginationMeta":
        if self.page_size > 0:
            import math  # noqa: PLC0415
            object.__setattr__(self, "total_pages", math.ceil(self.total_items / self.page_size))
        return self


class PaginatedResponse(CamelBase, Generic[T]):
    """Generic paginated list response.

    Usage:
        class SupplierListResponse(PaginatedResponse[SupplierResponse]):
            pass
    """
    data: list[T]
    pagination: PaginationMeta


# ---------------------------------------------------------------------------
# RFC 7807 Problem Details error response
# ---------------------------------------------------------------------------
class ErrorDetail(CamelBase):
    field: str | None = None
    message: str


class ErrorResponse(CamelBase):
    """RFC 7807 Problem Details — returned for all non-2xx responses."""
    type: AnyHttpUrl = Field(  # type: ignore[assignment]
        default="https://api.scvri.io/errors/generic",
        description="A URI reference identifying the problem type.",
    )
    title: str = Field(description="Human-readable summary of the problem type.")
    status: int = Field(description="HTTP status code.")
    error_code: str = Field(description="Machine-readable error code.")
    detail: str | list[ErrorDetail] | None = Field(
        default=None,
        description="Extended explanation or field-level validation errors.",
    )
    instance: str | None = Field(
        default=None,
        description="URI reference identifying this specific occurrence.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="X-Correlation-ID of the failed request.",
    )


# ---------------------------------------------------------------------------
# Cursor-based pagination (for high-volume endpoints)
# ---------------------------------------------------------------------------
class CursorPaginationMeta(CamelBase):
    next_cursor: str | None = Field(default=None, description="Opaque cursor for the next page.")
    prev_cursor: str | None = Field(default=None, description="Opaque cursor for the previous page.")
    has_more: bool = Field(default=False)
    page_size: int


class CursorPaginatedResponse(CamelBase, Generic[T]):
    data: list[T]
    pagination: CursorPaginationMeta


# ---------------------------------------------------------------------------
# Health / readiness check response
# ---------------------------------------------------------------------------
class ServiceDependencyHealth(CamelBase):
    name: str
    status: str  # "healthy" | "degraded" | "unhealthy"
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(CamelBase):
    status: str  # "healthy" | "degraded" | "unhealthy"
    service: str
    version: str
    environment: str
    timestamp: datetime
    dependencies: list[ServiceDependencyHealth] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audit event for inline responses
# ---------------------------------------------------------------------------
class AuditEventSchema(CamelBase):
    id: uuid.UUID
    event_type: str
    action: str
    resource_type: str | None
    resource_id: str | None
    actor_id: uuid.UUID | None
    actor_role: str | None
    event_time: datetime
    correlation_id: str | None
    new_values: dict[str, Any] | None = None
    old_values: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Soft-delete / status-change confirmation
# ---------------------------------------------------------------------------
class OperationResult(CamelBase):
    success: bool
    message: str
    resource_id: uuid.UUID | None = None
    affected_count: int | None = None
