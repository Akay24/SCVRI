"""FastAPI middleware stack for the SCVRI platform.

Middleware (applied outermost → innermost):
  1. CorrelationIDMiddleware — inject / propagate X-Correlation-ID header
  2. TenantResolutionMiddleware — decode JWT bearer, validate tenant, set RLS context
  3. PIISanitizationMiddleware — scrub PII patterns from structlog context vars
  4. AuditLogMiddleware — fire audit events for mutating HTTP methods

Usage in a FastAPI app factory:
    from scvri_shared.middleware import register_middleware
    register_middleware(app)
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from scvri_shared.exceptions import (
    AuthenticationError,
    SCVRIException,
    TenantIsolationError,
    TokenExpiredError,
)
from scvri_shared.logging import (
    correlation_id_ctx,
    get_logger,
    request_path_ctx,
    tenant_id_ctx,
    user_id_ctx,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helper to build RFC 7807 Problem Details JSON
# ---------------------------------------------------------------------------
def _problem_response(status: int, error_code: str, message: str, detail: object = None) -> JSONResponse:
    body = {
        "type": f"https://api.scvri.io/errors/{error_code.lower()}",
        "title": message,
        "status": status,
        "error_code": error_code,
    }
    if detail:
        body["detail"] = detail  # type: ignore[assignment]
    return JSONResponse(status_code=status, content=body)


# ===========================================================================
# 1. Correlation ID Middleware
# ===========================================================================
CORRELATION_ID_HEADER = "X-Correlation-ID"
X_REQUEST_ID_HEADER = "X-Request-ID"


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Injects a X-Correlation-ID into every request and echoes it on responses.

    Priority order for the correlation ID value:
      1. Incoming X-Correlation-ID header (from upstream gateway / caller)
      2. Incoming X-Request-ID header (AWS ALB, Kong)
      3. Newly generated UUID4

    The value is stored in :data:`scvri_shared.logging.correlation_id_ctx` so
    structlog automatically includes it in every log line during the request.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        correlation_id = (
            request.headers.get(CORRELATION_ID_HEADER)
            or request.headers.get(X_REQUEST_ID_HEADER)
            or str(uuid.uuid4())
        )
        correlation_id_ctx.set(correlation_id)
        request_path_ctx.set(request.url.path)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 1),
        )
        return response


# ===========================================================================
# 2. Tenant Resolution Middleware
# ===========================================================================
_ANON_PATHS = frozenset({
    "/health",
    "/ready",
    "/metrics",
    "/v1/auth/login",
    "/v1/auth/refresh",
    "/v1/auth/sso/callback",
    "/v1/auth/sso/metadata",
    "/docs",
    "/redoc",
    "/openapi.json",
})

_BEARER_PATTERN = re.compile(r"^Bearer (.+)$", re.IGNORECASE)


class TenantResolutionMiddleware(BaseHTTPMiddleware):
    """Extract the JWT bearer token, validate it, and set tenant context for RLS.

    On success:
    - Sets ``request.state.tenant_id``, ``request.state.user_id``, ``request.state.jwt_payload``
    - Populates structlog context vars (tenant_id_ctx, user_id_ctx)

    The RLS PostgreSQL session variable ``scvri.tenant_id`` is set per-query inside
    ``db.get_tenant_db()``; this middleware provides the decoded payload that
    ``get_tenant_db`` reads from ``request.state``.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        if request.url.path in _ANON_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        match = _BEARER_PATTERN.match(auth_header)
        if not match:
            return _problem_response(401, "AUTHENTICATION_FAILED", "Missing or malformed Authorization header.")

        token = match.group(1)
        try:
            from scvri_shared.security import verify_access_token  # noqa: PLC0415
            payload = verify_access_token(token)
        except TokenExpiredError:
            return _problem_response(401, "TOKEN_EXPIRED", "Access token has expired. Please refresh.")
        except AuthenticationError as exc:
            return _problem_response(401, exc.error_code, exc.message)

        tenant_id = payload.get("tid") or payload.get("tenant_id")
        user_id = payload.get("sub")
        if not tenant_id or not user_id:
            return _problem_response(401, "AUTHENTICATION_FAILED", "Token missing tenant or subject claim.")

        # Paranoia: validate UUID format before it touches the DB
        try:
            uuid.UUID(tenant_id)
            uuid.UUID(user_id)
        except ValueError:
            return _problem_response(401, "AUTHENTICATION_FAILED", "Malformed tenant or subject claim.")

        request.state.tenant_id = tenant_id
        request.state.user_id = user_id
        request.state.role = payload.get("role")
        request.state.scopes = payload.get("scopes", [])
        request.state.jwt_payload = payload

        tenant_id_ctx.set(tenant_id)
        user_id_ctx.set(user_id)

        return await call_next(request)


# ===========================================================================
# 3. PII Sanitisation Middleware
# ===========================================================================
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[EMAIL]"),
    (re.compile(r"\+?\d[\d\s\-().]{7,}\d"), "[PHONE]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
]


def sanitise_pii(text: str) -> str:
    """Replace recognised PII patterns in *text* with safe placeholders."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class PIISanitizationMiddleware(BaseHTTPMiddleware):
    """Sanitise structlog context vars that may contain PII before log emission.

    This operates on string values injected into the log context (path, query string).
    Body content is never logged, so this covers the common URL-based PII leak vectors.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        # Sanitise the request path before it ends up in logs
        safe_path = sanitise_pii(str(request.url.path))
        request_path_ctx.set(safe_path)
        return await call_next(request)


# ===========================================================================
# 4. Audit Log Middleware
# ===========================================================================
_AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Emit an audit event to the Kafka ``audit.events`` topic for every
    mutating request that completes with a 2xx status.

    The event contains method, path, tenant_id, user_id, role, correlation_id,
    and HTTP status.  Body diffing (old_values / new_values) is handled within
    individual service CRUD layers — this middleware provides the coarse-grained
    HTTP-level audit trail required for SOC 2 CC6.8 and GDPR Art. 30.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        response = await call_next(request)

        if request.method not in _AUDITED_METHODS:
            return response

        if not (200 <= response.status_code < 300):
            return response

        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = getattr(request.state, "user_id", None)
        role = getattr(request.state, "role", None)

        if not tenant_id:
            return response

        try:
            from scvri_shared.kafka import get_producer  # noqa: PLC0415
            producer = await get_producer()
            await producer.publish(
                topic="audit.events",
                key=tenant_id,
                value={
                    "event_type": "http.mutation",
                    "method": request.method,
                    "path": str(request.url.path),
                    "status_code": response.status_code,
                    "tenant_id": tenant_id,
                    "actor_id": user_id,
                    "actor_role": role,
                    "correlation_id": correlation_id_ctx.get(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("audit.kafka_publish_failed", error=str(exc))

        return response


# ===========================================================================
# Global exception handler (register on FastAPI app)
# ===========================================================================
async def scvri_exception_handler(request: Request, exc: SCVRIException) -> JSONResponse:
    """Convert SCVRIException subclasses to RFC 7807 JSON responses."""
    log.warning(
        "scvri.exception",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        path=request.url.path,
    )
    return _problem_response(exc.status_code, exc.error_code, exc.message, exc.detail)


# ===========================================================================
# Convenience — register all middleware + exception handler on a FastAPI app
# ===========================================================================
def register_middleware(app: ASGIApp) -> None:
    """Apply middleware stack and exception handler to *app*.

    Call this in your FastAPI app factory after the app is created but before
    ``include_router`` calls.

    Order matters — middleware wraps outermost-first, so add in reverse order:
    innermost (PII Sanitisation) → Tenant Resolution → Correlation ID
    """
    from fastapi import FastAPI  # noqa: PLC0415

    if not isinstance(app, FastAPI):
        raise TypeError("register_middleware expects a FastAPI instance.")

    # AuditLog (inner — needs tenant context from TenantResolution)
    app.add_middleware(AuditLogMiddleware)
    # PII Sanitisation
    app.add_middleware(PIISanitizationMiddleware)
    # Tenant Resolution
    app.add_middleware(TenantResolutionMiddleware)
    # Correlation ID (outermost — wraps everything)
    app.add_middleware(CorrelationIDMiddleware)

    # Global exception handler
    app.add_exception_handler(SCVRIException, scvri_exception_handler)  # type: ignore[arg-type]


# Backward-compatible middleware aliases
RequestIDMiddleware = CorrelationIDMiddleware
TenantRLSMiddleware = TenantResolutionMiddleware

