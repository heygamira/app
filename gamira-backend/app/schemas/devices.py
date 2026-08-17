"""Request and response models for device registration.

``DeviceOut`` has no ``push_token`` field, and that is deliberate: the token is
a send credential. It goes in and never comes out.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.models.enums import DevicePlatform, DeviceStatus
from app.schemas.common import ApiModel


class DeviceRegister(BaseModel):
    # The client's own stable id for this installation. Re-registering with the
    # same one updates the device instead of creating another.
    install_id: str = Field(min_length=8, max_length=128)
    platform: DevicePlatform
    push_token: str | None = Field(default=None, max_length=4096)
    app_version: str | None = Field(default=None, max_length=32)
    device_label: str | None = Field(default=None, max_length=120)
    locale: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)


class DeviceOut(ApiModel):
    id: uuid.UUID
    install_id: str
    platform: DevicePlatform
    app_version: str | None = None
    device_label: str | None = None
    status: DeviceStatus
    # Present so a support conversation can identify a device without the token
    # ever being shown or transmitted.
    push_token_fingerprint: str | None = None
    push_token_updated_at: dt.datetime | None = None
    push_token_invalid_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None
    created_at: dt.datetime


__all__ = ["DeviceOut", "DeviceRegister"]
