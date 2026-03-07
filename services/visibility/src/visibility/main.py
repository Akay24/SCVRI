"""Visibility service — FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from scvri_shared.logging import configure_logging
from scvri_shared.kafka import get_producer
from scvri_shared.middleware import register_middleware

from visibility.routers.purchase_orders import router as po_router
from visibility.routers.shipments import router as shipments_router
from visibility.routers.telemetry import router as telemetry_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()

    # Warm up Kafka producer
    async with get_producer():
        pass

    # Start Kafka consumers as background tasks
    from visibility.workers.kafka_consumers import start_all_consumers  # noqa: PLC0415
    consumer_tasks = await start_all_consumers()

    app.state.consumer_tasks = consumer_tasks
    yield

    # Tear down — cancel consumer tasks
    for task in consumer_tasks:
        task.cancel()


def create_app() -> FastAPI:
    application = FastAPI(
        title="SCVRI Visibility Service",
        version="0.1.0",
        description=(
            "Supply Chain Visibility — purchase order state machine, "
            "shipment tracking, IoT telemetry ingest, ERP integration."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    register_middleware(application)

    application.include_router(po_router, prefix="/v1")
    application.include_router(shipments_router, prefix="/v1")
    application.include_router(telemetry_router, prefix="/v1")

    @application.get("/health", tags=["Health"], include_in_schema=False)
    async def health() -> JSONResponse:
        return JSONResponse({"status": "healthy", "service": "visibility"})

    @application.get("/ready", tags=["Health"], include_in_schema=False)
    async def ready() -> JSONResponse:
        from sqlalchemy import text  # noqa: PLC0415
        from visibility.dependencies import _async_session  # noqa: PLC0415
        try:
            async with _async_session() as db:
                await db.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready"})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"status": "not_ready", "detail": str(exc)}, status_code=503)

    return application


app = create_app()
