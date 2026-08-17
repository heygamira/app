"""Registering, rotating and revoking a person's devices.

A device belongs to the user who registered it, and only that user can see or
change it. There is no endpoint that lists another person's devices, because
"which phones does my mother carry" is not a question this product answers.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.devices import RegisteredDevice
from app.models.enums import DevicePlatform, DeviceStatus

logger = get_logger(__name__)


async def register_device(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    install_id: str,
    platform: DevicePlatform,
    push_token: str | None = None,
    app_version: str | None = None,
    device_label: str | None = None,
    locale: str | None = None,
    timezone: str | None = None,
    now: dt.datetime | None = None,
) -> tuple[RegisteredDevice, bool]:
    """Create or update this user's record for one installation.

    Returns the device and whether it was newly created. Calling this on every
    app start is the intended use: it refreshes ``last_seen_at`` and picks up a
    rotated push token without producing a second row.
    """
    now = now or utcnow()
    existing = await session.execute(
        select(RegisteredDevice).where(
            RegisteredDevice.user_id == user_id,
            RegisteredDevice.install_id == install_id,
        )
    )
    device = existing.scalar_one_or_none()
    created = device is None

    if device is None:
        device = RegisteredDevice(
            user_id=user_id, install_id=install_id, platform=platform
        )
        session.add(device)

    device.platform = platform
    device.app_version = app_version or device.app_version
    device.device_label = device_label or device.device_label
    device.locale = locale or device.locale
    device.timezone = timezone or device.timezone
    device.last_seen_at = now
    # Re-registering an installation is how a signed-out phone comes back.
    device.status = DeviceStatus.ACTIVE
    device.revoked_at = None

    rotated = device.set_push_token(push_token, now=now) if push_token else False
    await session.flush()

    logger.info(
        "device_registered",
        extra={
            "device_id": str(device.id),
            "platform": platform.value,
            "created": created,
            "token_rotated": rotated,
            # The fingerprint, never the token.
            "device": device.push_token_fingerprint,
        },
    )
    return device, created


async def revoke_device(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> RegisteredDevice:
    now = now or utcnow()
    device = await session.get(RegisteredDevice, device_id)
    if device is None or device.user_id != user_id:
        # Same answer either way: a caller must not learn that a device id
        # belonging to somebody else exists.
        raise NotFound("The requested device does not exist.")

    device.status = DeviceStatus.REVOKED
    device.revoked_at = now
    # The token is dropped, not just marked: a revoked device should not be
    # reachable by a bug that ignores `status`.
    device.push_token = None
    device.push_token_fingerprint = None
    await session.flush()
    logger.info("device_revoked", extra={"device_id": str(device.id)})
    return device


async def list_devices(
    session: AsyncSession, *, user_id: uuid.UUID
) -> list[RegisteredDevice]:
    rows = await session.execute(
        select(RegisteredDevice)
        .where(RegisteredDevice.user_id == user_id)
        .order_by(RegisteredDevice.created_at)
    )
    return list(rows.scalars())


__all__ = ["list_devices", "register_device", "revoke_device"]
