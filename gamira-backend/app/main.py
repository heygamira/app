"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_engine

logger = get_logger(__name__)

DESCRIPTION = """
The Gamira backend. One authoritative API for the Parent App, the Family
Dashboard and the website.

Authentication: send `Authorization: Bearer <token>`. In local development with
`AUTH_MODE=dev`, the token is `dev:<subject>` — for example `dev:family-owner`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "application_start",
        extra={
            "environment": settings.app_env,
            "auth_mode": settings.auth_mode,
            "version": __version__,
        },
    )
    if settings.auth_mode == "dev":
        logger.warning(
            "dev_auth_enabled",
            extra={"detail": "Bearer tokens are not verified. Local use only."},
        )
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Never "*": these responses carry family health data and the clients
        # send credentials.
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-Id",
        ],
        expose_headers=["X-Request-Id"],
        max_age=600,
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
