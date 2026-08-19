"""Liveness and dependency health."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.deps import SessionDep, SettingsDep
from app.core.logging import get_logger
from app.schemas.common import HealthStatus

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


async def _database_ok(session: AsyncSession, *, log_event: str) -> bool:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error(log_event, extra={"error": str(exc)})
        return False
    return True


@router.get("/health", response_model=HealthStatus)
async def health(session: SessionDep, settings: SettingsDep) -> HealthStatus:
    """Report process health and whether the database actually answers.

    A degraded database is reported as ``degraded`` with HTTP 200 so uptime
    checks can distinguish "the process is up but its dependency is not" from a
    total outage. Liveness only — whether the *process* is alive, not whether
    it should currently receive traffic. See ``/ready`` for that.
    """
    ok = await _database_ok(session, log_event="health_database_check_failed")
    return HealthStatus(
        status="ok" if ok else "degraded",
        version=__version__,
        environment=settings.app_env,
        database="ok" if ok else "unavailable",
    )


@router.get("/ready")
async def ready(session: SessionDep) -> JSONResponse:
    """Readiness: should traffic be routed here right now.

    Unlike ``/health``, an unreachable database is a 503 here — this is the
    endpoint a Cloud Run/load-balancer readiness probe should point at, so a
    replica that can't reach the database stops receiving requests instead of
    reporting itself healthy while failing every real one.
    """
    ok = await _database_ok(session, log_event="readiness_database_check_failed")
    if not ok:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ready"})
