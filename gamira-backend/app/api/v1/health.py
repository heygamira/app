"""Liveness and dependency health."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import SessionDep, SettingsDep
from app.core.logging import get_logger
from app.schemas.common import HealthStatus

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health", response_model=HealthStatus)
async def health(session: SessionDep, settings: SettingsDep) -> HealthStatus:
    """Report process health and whether the database actually answers.

    A degraded database is reported as ``degraded`` with HTTP 200 so uptime
    checks can distinguish "the process is up but its dependency is not" from a
    total outage.
    """
    database = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("health_database_check_failed", extra={"error": str(exc)})
        database = "unavailable"

    return HealthStatus(
        status="ok" if database == "ok" else "degraded",
        version=__version__,
        environment=settings.app_env,
        database=database,
    )
