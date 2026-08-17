"""Creating notifications, and getting them to devices.

One event produces up to two rows per person, and the difference between them
is the whole point of this module:

* an ``in_app`` row is the inbox item. It exists the moment the event does, and
  it reaches somebody when they next open Gamira. Nothing more is claimed.
* a ``push`` row is a delivery job. It has real attempts behind it, one per
  registered device, each recorded with its outcome in
  ``notification_delivery_attempts``.

``GET /notifications`` returns only the first kind, because that is what an
inbox is. The second kind is machinery.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.care import NotificationDelivery, NotificationDeliveryAttempt
from app.models.devices import RegisteredDevice
from app.models.enums import (
    DeliveryAttemptStatus,
    DeviceStatus,
    MembershipStatus,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.models.identity import FamilyMembership
from app.notifications.provider import PushMessage, PushProvider, get_push_provider

logger = get_logger(__name__)

PUSH_SUFFIX = ":push"


@dataclass
class NotificationRequest:
    """One thing to tell one person."""

    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None = None
    dedupe_key: str = ""
    family_id: uuid.UUID | None = None
    senior_profile_id: uuid.UUID | None = None
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    # Off by default: most notifications should not wake a phone at night.
    high_priority: bool = False
    push: bool = True


async def create_notification(
    session: AsyncSession,
    request: NotificationRequest,
    *,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> tuple[NotificationDelivery | None, NotificationDelivery | None]:
    """Create the in-app record and, when wanted, its push counterpart.

    Returns ``(in_app, push)``, either of which is ``None`` when a row with
    that dedupe key already exists. That is the exactly-once guarantee the
    worker relies on: a retried job re-derives the same keys and creates
    nothing.
    """
    settings = settings or get_settings()
    now = now or utcnow()

    in_app = await _create_row(
        session,
        request,
        channel=NotificationChannel.IN_APP,
        dedupe_key=request.dedupe_key,
        now=now,
    )
    push: NotificationDelivery | None = None
    if request.push:
        push = await _create_row(
            session,
            request,
            channel=NotificationChannel.PUSH,
            dedupe_key=f"{request.dedupe_key}{PUSH_SUFFIX}",
            now=now,
            max_attempts=settings.job_max_attempts,
        )
    return in_app, push


async def _create_row(
    session: AsyncSession,
    request: NotificationRequest,
    *,
    channel: NotificationChannel,
    dedupe_key: str,
    now: dt.datetime,
    max_attempts: int = 5,
) -> NotificationDelivery | None:
    existing = await session.execute(
        select(NotificationDelivery.id).where(
            NotificationDelivery.dedupe_key == dedupe_key
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    row = NotificationDelivery(
        user_id=request.user_id,
        family_id=request.family_id,
        senior_profile_id=request.senior_profile_id,
        type=request.type,
        channel=channel,
        title=request.title,
        body=request.body,
        related_entity_type=request.related_entity_type,
        related_entity_id=request.related_entity_id,
        dedupe_key=dedupe_key[:160],
        max_attempts=max_attempts,
    )
    if channel is NotificationChannel.IN_APP:
        # Visible in the app from now on. Not "delivered": a closed app has
        # received nothing, and `delivered_at` stays null to say so.
        row.status = NotificationStatus.SENT
        row.sent_at = now
    else:
        row.status = NotificationStatus.QUEUED
        row.next_attempt_at = now
    session.add(row)
    await session.flush()
    return row


async def notify_family(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    template: NotificationRequest,
    exclude_user_ids: Sequence[uuid.UUID] = (),
    dedupe_prefix: str,
) -> list[uuid.UUID]:
    """Tell every other active member of a family. Returns who was told."""
    excluded = set(exclude_user_ids)
    rows = await session.execute(
        select(FamilyMembership.user_id).where(
            FamilyMembership.family_id == family_id,
            FamilyMembership.status == MembershipStatus.ACTIVE,
        )
    )
    notified: list[uuid.UUID] = []
    for user_id in rows.scalars():
        if user_id in excluded:
            continue
        request = NotificationRequest(
            **{
                **template.__dict__,
                "user_id": user_id,
                "family_id": family_id,
                "dedupe_key": f"{dedupe_prefix}:{user_id}",
            }
        )
        await create_notification(session, request)
        notified.append(user_id)
    return notified


# --------------------------------------------------------------------------- #
# Push delivery
# --------------------------------------------------------------------------- #


async def deliverable_devices(
    session: AsyncSession, user_id: uuid.UUID
) -> list[RegisteredDevice]:
    rows = await session.execute(
        select(RegisteredDevice).where(
            RegisteredDevice.user_id == user_id,
            RegisteredDevice.status == DeviceStatus.ACTIVE,
            RegisteredDevice.push_token.is_not(None),
            RegisteredDevice.push_token_invalid_at.is_(None),
        )
    )
    return list(rows.scalars())


async def deliver_push(
    session: AsyncSession,
    notification: NotificationDelivery,
    *,
    provider: PushProvider | None = None,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> NotificationStatus:
    """Try every device this person has, once, and record what happened.

    The outcome of the whole notification is the best outcome across devices:
    one phone accepting the message is a delivery even if a stale tablet token
    was rejected alongside it.
    """
    settings = settings or get_settings()
    provider = provider or get_push_provider(settings)
    now = now or utcnow()

    if notification.channel is not NotificationChannel.PUSH:
        raise ValueError("deliver_push was given an in-app notification row.")

    notification.attempt_count += 1
    attempt_number = notification.attempt_count

    devices = await deliverable_devices(session, notification.user_id)
    already = await _devices_already_delivered(session, notification.id)

    if not devices:
        # Nobody has registered a device. That is not a failure to retry
        # forever — there is nothing to send to.
        session.add(
            NotificationDeliveryAttempt(
                notification_delivery_id=notification.id,
                channel=NotificationChannel.PUSH,
                provider=provider.name,
                status=DeliveryAttemptStatus.SKIPPED,
                error_code="no_registered_device",
                attempt_number=attempt_number,
                attempted_at=now,
            )
        )
        notification.status = NotificationStatus.CANCELLED
        notification.last_error_code = "no_registered_device"
        notification.next_attempt_at = None
        await session.flush()
        return notification.status

    any_success = False
    any_retryable = False
    last_error: str | None = None

    for device in devices:
        if device.id in already:
            # This device already took the message. Sending again would be a
            # duplicate notification on somebody's lock screen.
            continue
        token = device.push_token or ""
        result = await provider.send(
            token=token,
            message=PushMessage(
                title=notification.title,
                body=notification.body or "",
                data=_push_data(notification),
                collapse_key=notification.dedupe_key[:64],
                high_priority=notification.type
                in (NotificationType.SOS, NotificationType.SOS_ESCALATION),
            ),
        )
        session.add(
            NotificationDeliveryAttempt(
                notification_delivery_id=notification.id,
                device_id=device.id,
                channel=NotificationChannel.PUSH,
                provider=provider.name,
                status=result.status,
                provider_message_id=result.message_id,
                error_code=result.error_code,
                device_token_fingerprint=device.push_token_fingerprint,
                attempt_number=attempt_number,
                latency_ms=result.latency_ms,
                attempted_at=now,
            )
        )
        if result.succeeded:
            any_success = True
            device.last_seen_at = device.last_seen_at or now
            if notification.provider_reference is None and result.message_id:
                notification.provider_reference = result.message_id[:200]
        elif result.status is DeliveryAttemptStatus.TOKEN_INVALID:
            # The app was uninstalled or the token rotated. Retiring it here is
            # what stops this queue growing forever.
            device.push_token_invalid_at = now
            last_error = result.error_code
            logger.info(
                "push_token_revoked",
                extra={
                    "device_id": str(device.id),
                    "device": device.push_token_fingerprint,
                    "error_code": result.error_code,
                },
            )
        elif result.status is DeliveryAttemptStatus.RETRYABLE:
            any_retryable = True
            last_error = result.error_code
        else:
            last_error = result.error_code

    if any_success:
        notification.status = NotificationStatus.SENT
        notification.sent_at = notification.sent_at or now
        notification.delivered_at = now
        notification.next_attempt_at = None
        notification.last_error_code = None
    elif any_retryable and notification.attempt_count < notification.max_attempts:
        notification.status = NotificationStatus.QUEUED
        notification.last_error_code = (last_error or "retryable")[:64]
        notification.next_attempt_at = now + dt.timedelta(
            seconds=_push_backoff(notification.attempt_count, settings)
        )
    else:
        notification.status = NotificationStatus.FAILED
        notification.last_error_code = (last_error or "delivery_failed")[:64]
        notification.next_attempt_at = None

    await session.flush()
    logger.info(
        "push_delivery_finished",
        extra={
            "notification_id": str(notification.id),
            "notification_type": notification.type.value,
            "attempt": attempt_number,
            "devices": len(devices),
            "outcome": notification.status.value,
        },
    )
    return notification.status


async def _devices_already_delivered(
    session: AsyncSession, notification_id: uuid.UUID
) -> set[uuid.UUID]:
    rows = await session.execute(
        select(NotificationDeliveryAttempt.device_id).where(
            NotificationDeliveryAttempt.notification_delivery_id == notification_id,
            NotificationDeliveryAttempt.status == DeliveryAttemptStatus.SUCCEEDED,
        )
    )
    return {device_id for device_id in rows.scalars() if device_id is not None}


def _push_data(notification: NotificationDelivery) -> dict[str, str]:
    """Only what the app needs to open the right screen."""
    data = {
        "notification_id": str(notification.id),
        "type": notification.type.value,
    }
    if notification.related_entity_type:
        data["entity_type"] = notification.related_entity_type
    if notification.related_entity_id:
        data["entity_id"] = str(notification.related_entity_id)
    if notification.senior_profile_id:
        data["senior_profile_id"] = str(notification.senior_profile_id)
    return data


def _push_backoff(attempt: int, settings: Settings) -> float:
    return min(
        settings.job_retry_base_seconds * (2 ** max(0, attempt - 1)),
        settings.job_retry_max_seconds,
    )


async def pending_push_notifications(
    session: AsyncSession, *, limit: int = 50, now: dt.datetime | None = None
) -> list[NotificationDelivery]:
    now = now or utcnow()
    rows = await session.execute(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.channel == NotificationChannel.PUSH,
            NotificationDelivery.status == NotificationStatus.QUEUED,
            NotificationDelivery.next_attempt_at.is_not(None),
            NotificationDelivery.next_attempt_at <= now,
        )
        .order_by(NotificationDelivery.next_attempt_at)
        .limit(limit)
    )
    return list(rows.scalars())


__all__ = [
    "NotificationRequest",
    "create_notification",
    "deliver_push",
    "deliverable_devices",
    "notify_family",
    "pending_push_notifications",
]
