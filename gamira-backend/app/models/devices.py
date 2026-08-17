"""Registered devices and their push tokens.

A device is *owned by a user*, not by a family. That is what makes revocation
meaningful: signing out one phone stops notifications reaching that phone, and
nothing about the family's data changes.

The FCM token is a bearer credential for sending to that device. It is stored
so a worker can use it, never returned by any endpoint, and never written to a
log — only its fingerprint is, which is enough to correlate a failure with a
row and useless to anyone who reads it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import UtcDateTime
from app.models.enums import DevicePlatform, DeviceStatus


def token_fingerprint(token: str) -> str:
    """A short, stable, non-reversible label for one push token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class RegisteredDevice(UUIDPrimaryKey, Timestamps, Base):
    """One installation of a Gamira app on one device.

    ``install_id`` is the client's own stable identifier for its installation.
    Keying on it rather than on the push token means a token rotation updates
    this row instead of creating a second one, so a person who has used the
    same phone for a year has one device record, not two hundred.
    """

    __tablename__ = "registered_devices"
    __table_args__ = (
        Index(
            "uq_registered_devices_user_install",
            "user_id",
            "install_id",
            unique=True,
        ),
        Index("ix_registered_devices_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    install_id: Mapped[str] = mapped_column(String(128))
    platform: Mapped[DevicePlatform] = mapped_column(
        Enum(DevicePlatform, native_enum=False, length=16)
    )
    app_version: Mapped[str | None] = mapped_column(String(32))
    device_label: Mapped[str | None] = mapped_column(String(120))
    locale: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str | None] = mapped_column(String(64))

    # Held for the worker, returned to nobody.
    push_token: Mapped[str | None] = mapped_column(Text())
    push_token_fingerprint: Mapped[str | None] = mapped_column(String(32), index=True)
    push_token_updated_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    push_token_invalid_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False, length=16), default=DeviceStatus.ACTIVE
    )
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    @property
    def can_receive_push(self) -> bool:
        return (
            self.status is DeviceStatus.ACTIVE
            and bool(self.push_token)
            and self.push_token_invalid_at is None
        )

    def set_push_token(self, token: str | None, *, now: dt.datetime) -> bool:
        """Rotate the token. Returns True when it actually changed."""
        fingerprint = token_fingerprint(token) if token else None
        if fingerprint == self.push_token_fingerprint:
            return False
        self.push_token = token
        self.push_token_fingerprint = fingerprint
        self.push_token_updated_at = now
        # A new token is assumed good until a provider says otherwise.
        self.push_token_invalid_at = None
        return True


__all__ = ["RegisteredDevice", "token_fingerprint"]
