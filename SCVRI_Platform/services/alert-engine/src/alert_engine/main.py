"""Alert Engine — FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scvri_shared.config import settings
from scvri_shared.logging import configure_logging, get_logger
from scvri_shared.middleware import RequestIDMiddleware, TenantRLSMiddleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start Kafka consumers on launch; clean up on shutdown."""
    from alert_engine.workers.kafka_consumers import start_consumers_background  # noqa: PLC0415

    configure_logging()
    log.info("alert_engine.startup", version=app.version)

    consumer_task = start_consumers_background()

    yield

    # Shutdown
    consumer_task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(consumer_task), timeout=5)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    log.info("alert_engine.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SCVRI Alert Engine",
        version="1.0.0",
        description=(
            "Multi-tenant alert lifecycle management — rules, notifications, "
            "escalation, suppression, and multi-channel delivery."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantRLSMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    from alert_engine.routers.alerts import router as alerts_router  # noqa: PLC0415
    from alert_engine.routers.notifications import router as notifications_router  # noqa: PLC0415
    from alert_engine.routers.rules import router as rules_router  # noqa: PLC0415

    API_PREFIX = "/api/v1"

    app.include_router(alerts_router, prefix=API_PREFIX)
    app.include_router(rules_router, prefix=API_PREFIX)
    app.include_router(notifications_router, prefix=API_PREFIX)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "service": "alert-engine"}

    return app


app = create_app()
