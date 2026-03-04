"""Domain exception hierarchy for the SCVRI platform.

All exceptions map cleanly to HTTP status codes so FastAPI exception handlers
can serialise them into RFC 7807 Problem Details responses.

Usage:
    from scvri_shared.exceptions import NotFoundError, TenantIsolationError
    raise NotFoundError("Supplier", supplier_id)
"""
from __future__ import annotations

from typing import Any


class SCVRIException(Exception):
    """Base exception for all SCVRI platform errors.

    Attributes:
        message:     Human-readable error description.
        error_code:  Machine-readable code (e.g. "SUPPLIER_NOT_FOUND").
        status_code: HTTP status code for FastAPI error handlers.
        detail:      Extra structured context (logged but not always surfaced to clients).
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        *,
        error_code: str | None = None,
        detail: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        if error_code is not None:
            self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(error_code={self.error_code!r}, message={self.message!r})"


# ---------------------------------------------------------------------------
# 400 Bad Request
# ---------------------------------------------------------------------------
class ValidationError(SCVRIException):
    """Input failed business rule validation."""

    status_code = 400
    error_code = "VALIDATION_ERROR"

    def __init__(
        self,
        message: str = "Validation failed.",
        *,
        field: str | None = None,
        detail: Any | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.field = field


class DuplicateError(SCVRIException):
    """Attempt to create a resource that already exists."""

    status_code = 409
    error_code = "DUPLICATE_RESOURCE"

    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(f"{resource} with identifier '{identifier}' already exists.")
        self.resource = resource
        self.identifier = identifier


# ---------------------------------------------------------------------------
# 401 Unauthorised
# ---------------------------------------------------------------------------
class AuthenticationError(SCVRIException):
    """Missing, invalid, or insufficiently trusted credentials."""

    status_code = 401
    error_code = "AUTHENTICATION_FAILED"


class TokenExpiredError(AuthenticationError):
    """JWT or refresh token has passed its expiry."""

    error_code = "TOKEN_EXPIRED"


class MFARequiredError(AuthenticationError):
    """Endpoint requires MFA but second factor was not presented."""

    error_code = "MFA_REQUIRED"
    status_code = 401


# ---------------------------------------------------------------------------
# 403 Forbidden
# ---------------------------------------------------------------------------
class ForbiddenError(SCVRIException):
    """Authenticated user does not have permission for the requested action."""

    status_code = 403
    error_code = "FORBIDDEN"

    def __init__(
        self,
        action: str = "unknown",
        resource: str = "resource",
        *,
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            f"You do not have permission to perform '{action}' on {resource}.",
            detail=detail,
        )
        self.action = action
        self.resource = resource


class TenantIsolationError(ForbiddenError):
    """RLS or application-layer tenant isolation violation detected."""

    error_code = "TENANT_ISOLATION_VIOLATION"

    def __init__(self, detail: Any | None = None) -> None:
        SCVRIException.__init__(
            self,
            "Cross-tenant data access attempt detected and blocked.",
            error_code=self.error_code,
            detail=detail,
        )


class InsufficientScopeError(ForbiddenError):
    """Token scopes do not cover the requested operation."""

    error_code = "INSUFFICIENT_SCOPE"

    def __init__(self, required_scope: str) -> None:
        SCVRIException.__init__(
            self,
            f"Token is missing required scope: '{required_scope}'.",
            error_code=self.error_code,
        )


# ---------------------------------------------------------------------------
# 404 Not Found
# ---------------------------------------------------------------------------
class NotFoundError(SCVRIException):
    """Requested resource does not exist (or is not visible to this tenant)."""

    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"

    def __init__(self, resource: str, identifier: Any = None) -> None:
        msg = f"{resource} not found"
        if identifier is not None:
            msg = f"{resource} '{identifier}' not found"
        super().__init__(msg)
        self.resource = resource
        self.identifier = identifier


# ---------------------------------------------------------------------------
# 409 Conflict
# ---------------------------------------------------------------------------
class StateTransitionError(SCVRIException):
    """Invalid state machine transition."""

    status_code = 409
    error_code = "INVALID_STATE_TRANSITION"

    def __init__(self, from_state: str, to_state: str, resource: str) -> None:
        super().__init__(
            f"Cannot transition {resource} from '{from_state}' to '{to_state}'."
        )
        self.from_state = from_state
        self.to_state = to_state


# ---------------------------------------------------------------------------
# 422 Unprocessable Entity
# ---------------------------------------------------------------------------
class BusinessRuleError(SCVRIException):
    """Action violates a business rule (not a schema validation error)."""

    status_code = 422
    error_code = "BUSINESS_RULE_VIOLATION"


# ---------------------------------------------------------------------------
# 429 Too Many Requests
# ---------------------------------------------------------------------------
class RateLimitError(SCVRIException):
    """Client has exceeded the allowed request rate."""

    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, retry_after_seconds: int = 60) -> None:
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after_seconds} seconds."
        )
        self.retry_after_seconds = retry_after_seconds


# ---------------------------------------------------------------------------
# 503 Service Unavailable
# ---------------------------------------------------------------------------
class ExternalServiceError(SCVRIException):
    """Downstream service call failed."""

    status_code = 503
    error_code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, service_name: str, detail: Any | None = None) -> None:
        super().__init__(
            f"External service '{service_name}' is unavailable.",
            detail=detail,
        )
        self.service_name = service_name


class CircuitBreakerOpenError(ExternalServiceError):
    """Circuit breaker is open — requests to this service are fast-failing."""

    error_code = "CIRCUIT_BREAKER_OPEN"

    def __init__(self, service_name: str, reset_at_iso: str | None = None) -> None:
        SCVRIException.__init__(
            self,
            f"Circuit breaker for '{service_name}' is open. Requests are blocked.",
            error_code=self.error_code,
            detail={"reset_at": reset_at_iso},
        )
        self.service_name = service_name


# ---------------------------------------------------------------------------
# Compliance / GDPR specific
# ---------------------------------------------------------------------------
class GDPRSLAExceededError(SCVRIException):
    """GDPR erasure or rights request has exceeded its 30-day SLA."""

    status_code = 500
    error_code = "GDPR_SLA_EXCEEDED"


class PIIAccessDeniedError(ForbiddenError):
    """Attempt to access PII data without the required DPO-level role."""

    error_code = "PII_ACCESS_DENIED"

    def __init__(self) -> None:
        SCVRIException.__init__(
            self,
            "Access to PII data requires explicit Data Protection Officer authorisation.",
            error_code=self.error_code,
        )
