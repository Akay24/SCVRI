"""Integration service — main FastAPI application."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from integration.core.kafka_producer import get_producer, stop_producer
from integration.routers import erp_router, outbound_router, webhooks_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(application: FastAPI):  # type: ignore[type-arg]
    # Eagerly start Kafka producer so first-request latency is minimal
    await get_producer()
    yield
    await stop_producer()


app = FastAPI(
    title="SCVRI Integration Layer",
    description=(
        "Bidirectional integration hub — ERP pull sync (SAP / Oracle Fusion), "
        "inbound webhook ingestion with HMAC validation, event normalisation → Kafka, "
        "and outbound push delivery to external systems."
    ),
    version="1.0.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(erp_router, prefix=API_PREFIX)
app.include_router(webhooks_router, prefix=API_PREFIX)
app.include_router(outbound_router, prefix=API_PREFIX)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "integration"}
