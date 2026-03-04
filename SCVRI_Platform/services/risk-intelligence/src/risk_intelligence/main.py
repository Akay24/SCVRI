"""Risk Intelligence Engine — FastAPI application entry point.

Port: 8002
Prefix: /v1
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from scvri_shared.config import settings
from scvri_shared.logging import configure_logging, get_logger
from scvri_shared.middleware import register_middleware
from scvri_shared.kafka import get_producer

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("risk_intelligence_service.startup", version=settings.service_version)

    # Initialise Kafka producer (cached singleton)
    async with get_producer() as producer:
        app.state.kafka_producer = producer
        log.info("kafka_producer.ready")
        yield

    log.info("risk_intelligence_service.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SCVRI Risk Intelligence Engine",
        description="ML-powered supplier risk scoring, KRI management, and model registry.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    register_middleware(app)

    # ── Routers ─────────────────────────────────────────────────────────────
    from risk_intelligence.routers import risk_scores, kri, models  # noqa: PLC0415

    # Supplier-scoped risk & KRI endpoints
    app.include_router(
        risk_scores.router,
        prefix="/v1/suppliers",
        tags=["Risk Scores"],
    )
    app.include_router(
        kri.router,
        prefix="/v1/suppliers",
        tags=["KRI"],
    )
    # Model registry (not supplier-scoped)
    app.include_router(
        models.router,
        prefix="/v1",
        tags=["Model Registry"],
    )

    # ── Utility endpoints ────────────────────────────────────────────────────
    @app.get("/health", tags=["Ops"], summary="Liveness probe")
    async def health():
        return {"status": "ok", "service": "risk-intelligence"}

    @app.get("/ready", tags=["Ops"], summary="Readiness probe")
    async def ready():
        """Check database connectivity before advertising readiness."""
        from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        try:
            engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return {"status": "ready", "service": "risk-intelligence"}
        except Exception as exc:  # noqa: BLE001
            log.error("readiness_probe.failed", error=str(exc))
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "detail": str(exc)},
            )

    return app


app = create_app()
