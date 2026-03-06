"""Structured logging configuration using structlog.

Usage:
    from scvri_shared.logging import configure_logging, get_logger

    configure_logging()              # call once at app startup
    log = get_logger(__name__)
    log.info("supplier.created", supplier_id=str(s.id), tenant_id=str(tenant_id))

Features:
- JSON renderer in staging/production (sends to CloudWatch / Opensearch)
- Pretty console renderer in development
- Auto-injects: service_name, environment, correlation_id (from contextvars), tenant_id
- OpenTelemetry trace/span IDs injected when a trace is active
- Sensitive field masking (email, tax_id, token patterns)
"""
from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Context variables — set per-request in middleware
# ---------------------------------------------------------------------------
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
request_path_ctx: ContextVar[str] = ContextVar("request_path", default="-")

# ---------------------------------------------------------------------------
# Sensitive field masking
# ---------------------------------------------------------------------------
_SENSITIVE_KEYS = frozenset({
    "password", "password_hash", "hashed_password", "token", "secret",
    "access_token", "refresh_token", "api_key", "private_key", "totp_secret",
    "totp_secret_encrypted", "signing_secret_encrypted", "backup_codes_hash",
    "tax_id", "ssn", "credit_card",
})

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s\-().]{7,}\d")


def _mask_sensitive_values(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001, ARG001
    """Remove or mask sensitive keys from the log event dictionary."""
    for key in list(event_dict.keys()):
        if key in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def _inject_context(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001, ARG001
    """Inject correlation_id, tenant_id, user_id from context vars."""
    event_dict.setdefault("correlation_id", correlation_id_ctx.get())
    event_dict.setdefault("tenant_id", tenant_id_ctx.get())
    event_dict.setdefault("user_id", user_id_ctx.get())
    event_dict.setdefault("request_path", request_path_ctx.get())
    return event_dict


def _inject_otel_trace(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001, ARG001
    """Inject OpenTelemetry trace_id and span_id if a trace is active."""
    try:
        from opentelemetry import trace  # noqa: PLC0415
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            event_dict["trace_id"] = f"{ctx.trace_id:032x}"
            event_dict["span_id"] = f"{ctx.span_id:016x}"
    except ImportError:
        pass
    return event_dict


# ---------------------------------------------------------------------------
# Public configuration entry-point
# ---------------------------------------------------------------------------
def configure_logging(
    level: str | None = None,
    json_logs: bool | None = None,
) -> None:
    """Configure structlog and stdlib logging.

    Call once during application startup (e.g. in the FastAPI lifespan).

    Args:
        level:     Override log level (default: settings.LOG_LEVEL).
        json_logs: Override JSON mode (default: True unless ENVIRONMENT=development).
    """
    from scvri_shared.config import settings  # noqa: PLC0415 (avoid circular at module load)

    effective_level = (level or settings.log_level).upper()
    use_json = json_logs if json_logs is not None else settings.environment != "development"

    # Configure stdlib root logger so third-party libs' log records flow through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, effective_level, logging.INFO),
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_context,
        _inject_otel_trace,
        _mask_sensitive_values,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)  # type: ignore[assignment]

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, effective_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Suppress noisy third-party loggers below WARNING
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "aiokafka", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog BoundLogger pre-bound with *service_name*.

    Usage:
        log = get_logger(__name__)
        log.info("event.name", key=value, ...)
    """
    from scvri_shared.config import settings  # noqa: PLC0415

    return structlog.get_logger(name or "scvri").bind(
        service=settings.service_name,
        env=settings.environment,
    )
