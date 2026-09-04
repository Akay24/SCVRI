"""Supplier Management Service — FastAPI application factory.

Startup sequence:
  1. Configure logging (structlog)
  2. Start OpenTelemetry tracer
  3. Initialise Kafka producer
  4. Wire up middleware stack
  5. Register all routers

Shutdown sequence:
  1. Drain Kafka producer
  2. Close DB engine connection pool
"""
from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scvri_shared.config import settings
from scvri_shared.kafka import close_producer, init_producer
from scvri_shared.logging import configure_logging, get_logger
from scvri_shared.middleware import register_middleware
from scvri_shared.schemas import HealthResponse, ServiceDependencyHealth

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan context manager — runs on startup and shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    configure_logging()
    log.info("supplier_management.startup", version=settings.service_version)

    # OpenTelemetry
    _setup_otel()

    # Kafka producer singleton
    app.state.kafka_producer = await init_producer()
    log.info("supplier_management.kafka_ready")

    yield

    # --- SHUTDOWN ---
    await close_producer()
    log.info("supplier_management.shutdown")


def _setup_otel() -> None:
    with contextlib.suppress(ImportError):
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: PLC0415
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # noqa: PLC0415

        if not settings.otel_enabled:
            return

        resource = Resource.create({
            "service.name": settings.service_name,
            "service.version": settings.service_version,
            "deployment.environment": settings.environment,
        })
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor().instrument()
        SQLAlchemyInstrumentor().instrument()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    application = FastAPI(
        title="SCVRI Supplier Management Service",
        description="Supplier onboarding, document vault, scorecards, and certifications.",
        version=settings.service_version,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "X-Response-Time-Ms"],
    )

    # SCVRI middleware stack (CorrelationID + TenantResolution + PII + AuditLog)
    register_middleware(application)

    # Routers
    from supplier_management.routers import (  # noqa: PLC0415
        contacts,
        documents,
        onboarding,
        scorecards,
        suppliers,
    )
    API_PREFIXES = ["/api/v1/suppliers", "/v1/suppliers"]
    for prefix in API_PREFIXES:
        application.include_router(suppliers.router, prefix=prefix, tags=["Suppliers"])
        application.include_router(contacts.router, prefix=prefix, tags=["Contacts"])
        application.include_router(documents.router, prefix=prefix, tags=["Documents"])
        application.include_router(scorecards.router, prefix=prefix, tags=["Scorecards"])
        application.include_router(onboarding.router, prefix=prefix, tags=["Onboarding"])

    # Health endpoints (no auth required)
    _register_health_routes(application)

    return application


def _register_health_routes(app: FastAPI) -> None:
    from fastapi import Response  # noqa: PLC0415

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "healthy", "service": settings.service_name}

    @app.get("/ready", include_in_schema=False)
    async def readiness() -> HealthResponse:
        deps: list[ServiceDependencyHealth] = []

        # Check PostgreSQL
        try:
            from scvri_shared.db import get_async_engine  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415
            import time  # noqa: PLC0415

            engine = get_async_engine()
            t0 = time.perf_counter()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            deps.append(ServiceDependencyHealth(
                name="postgresql",
                status="healthy",
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            ))
        except Exception as exc:  # noqa: BLE001
            deps.append(ServiceDependencyHealth(name="postgresql", status="unhealthy", detail=str(exc)))

        # Check Redis
        try:
            import redis.asyncio as aioredis  # noqa: PLC0415
            import time  # noqa: PLC0415

            r = aioredis.from_url(settings.redis_url)
            t0 = time.perf_counter()
            async with r:
                await r.ping()
            deps.append(ServiceDependencyHealth(
                name="redis",
                status="healthy",
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            ))
        except Exception as exc:  # noqa: BLE001
            deps.append(ServiceDependencyHealth(name="redis", status="unhealthy", detail=str(exc)))

        overall = "healthy" if all(d.status == "healthy" for d in deps) else "degraded"
        return HealthResponse(
            status=overall,
            service=settings.service_name,
            version=settings.service_version,
            environment=settings.environment,
            timestamp=datetime.now(tz=timezone.utc),
            dependencies=deps,
        )


app = create_app()
