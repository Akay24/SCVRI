"""IAM Service — FastAPI application entrypoint (port 8000)."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scvri_shared.config import settings
from scvri_shared.logging import configure_logging, get_logger
from scvri_shared.middleware import RequestIDMiddleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    # Eagerly load RS256 keys to fail fast at startup rather than on first request
    from iam.core.security import get_private_key, get_public_key  # noqa: PLC0415
    get_private_key()
    get_public_key()
    log.info("iam.startup", version=app.version)
    yield
    log.info("iam.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SCVRI IAM Service",
        version="1.0.0",
        description=(
            "Identity & Access Management — JWT RS256 authentication, "
            "TOTP MFA, RBAC, and SCIM 2.0 user provisioning."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    # ── Routers ────────────────────────────────────────────────────────────────
    from iam.routers.auth import router as auth_router  # noqa: PLC0415
    from iam.routers.roles import router as roles_router  # noqa: PLC0415
    from iam.routers.scim import router as scim_router  # noqa: PLC0415
    from iam.routers.users import router as users_router  # noqa: PLC0415

    API_PREFIX = "/api/v1"

    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    app.include_router(roles_router, prefix=API_PREFIX)
    # SCIM endpoint uses its own /scim/v2 prefix (no API_PREFIX)
    app.include_router(scim_router)

    # ── Health check ───────────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "service": "iam"}

    # ── Public key endpoint (for other services to fetch RS256 pubkey) ────────
    @app.get("/.well-known/jwks.json", tags=["ops"])
    async def jwks() -> dict:
        """
        Return the RS256 public key in JWK format so downstream services
        can verify access tokens without calling the IAM service.
        """
        from jose import jwk  # noqa: PLC0415
        from iam.core.security import get_public_key  # noqa: PLC0415

        pub_key = get_public_key()
        key_obj = jwk.construct(pub_key, algorithm="RS256")
        key_dict = key_obj.to_dict()
        key_dict["use"] = "sig"
        key_dict["alg"] = "RS256"
        key_dict["kid"] = "scvri-iam-key-1"
        return {"keys": [key_dict]}

    return app


app = create_app()
