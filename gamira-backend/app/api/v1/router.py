"""Version 1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import ai, care, devices, families, me, medications, sos

api_router = APIRouter()
api_router.include_router(me.router)
api_router.include_router(families.router)
api_router.include_router(medications.router)
api_router.include_router(care.router)
api_router.include_router(sos.router)
api_router.include_router(devices.router)
api_router.include_router(ai.router)
