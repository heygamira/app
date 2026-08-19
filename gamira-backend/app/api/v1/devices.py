"""Device registration, and flags raised by a paired device.

Two things live here, and they are not the same thing.

**Registration** is how a phone or watch becomes something Gamira can send a
push to: a row owned by the signed-in user, holding a token that goes in and
never comes out, and can be rotated or revoked from the same device.

**A device flag** is a machine reporting that a number left a range someone
configured on it. The distinction it exists to keep:

* An **SOS** is a person asking for help. It is red, it interrupts, and it is
  never anything else.
* A **device flag** is shown, attributed to the device by name, and is not an
  emergency.

Gamira repeats the device's own words. It does not decide that a reading is
dangerous, and nothing here is a clinical judgement.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import NotFound
from app.db.base import utcnow
from app.models.enums import NotificationType
from app.models.identity import SeniorProfile
from app.schemas.care import DeviceFlagCreate, DeviceFlagOut
from app.schemas.devices import DeviceOut, DeviceRegister
from app.services import devices as device_service
from app.services import wellbeing as wellbeing_service
from app.services.authz import require_self_or_write_access
from app.services.notifications import NotificationRequest, notify_family
from app.services.realtime import publish_family_event
from app.services.timeline import record_audit

router = APIRouter(tags=["devices"])


@router.post("/devices", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceRegister, session: SessionDep, user: CurrentUser
) -> DeviceOut:
    """Register or refresh this installation, and rotate its push token.

    Safe to call on every app start. The same ``install_id`` updates the
    existing row rather than adding another, so a person who has used one phone
    for a year has one device record.
    """
    device, created = await device_service.register_device(
        session,
        user_id=user.id,
        install_id=payload.install_id,
        platform=payload.platform,
        push_token=payload.push_token,
        app_version=payload.app_version,
        device_label=payload.device_label,
        locale=payload.locale,
        timezone=payload.timezone,
    )
    await record_audit(
        session,
        action="device.register",
        actor_user_id=user.id,
        target_type="registered_device",
        target_id=device.id,
        # The fingerprint identifies the device in an audit trail; the token
        # itself is never written anywhere but its own column.
        metadata={
            "platform": payload.platform.value,
            "created": created,
            "device": device.push_token_fingerprint,
        },
    )
    return DeviceOut.model_validate(device)


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(session: SessionDep, user: CurrentUser) -> list[DeviceOut]:
    """The caller's own devices. There is no way to list anyone else's."""
    rows = await device_service.list_devices(session, user_id=user.id)
    return [DeviceOut.model_validate(row) for row in rows]


@router.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_device(
    device_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    """Stop sending to this device and drop its token."""
    device = await device_service.revoke_device(
        session, user_id=user.id, device_id=device_id
    )
    await record_audit(
        session,
        action="device.revoke",
        actor_user_id=user.id,
        target_type="registered_device",
        target_id=device.id,
    )


@router.post(
    "/seniors/{senior_id}/device-flags",
    response_model=DeviceFlagOut,
    status_code=status.HTTP_201_CREATED,
)
async def raise_device_flag(
    senior_id: uuid.UUID,
    payload: DeviceFlagCreate,
    session: SessionDep,
    user: CurrentUser,
) -> DeviceFlagOut:
    """Tell the family that a device flagged one of this person's readings.

    The wearer's own account may always do this — the watch is their device,
    the same reasoning that lets them confirm their own dose. Anyone else needs
    write access, and a caller outside the family gets a 404.

    Deliberately *not* an SOS: type `family_update`, no timeline entry, and
    wording that names the device as the one drawing the line.

    It now also opens a **wellbeing check** — a durable row saying a question
    is owed. Gamira asks it when the app is next open, and a rule in
    ``jobs/handlers/care.py`` tells the family if nobody answers. The flag
    itself kept no record at all before, which meant the one outcome worth
    catching — a flagged reading followed by silence — was invisible.
    """
    await require_self_or_write_access(
        session, user_id=user.id, senior_profile_id=senior_id
    )
    senior = await session.get(SeniorProfile, senior_id)
    if senior is None:  # pragma: no cover - the helper above already raised
        raise NotFound("The requested person does not exist.")

    flag_id = uuid.uuid4()
    raised_at = utcnow()
    device = payload.source_device or "their watch"
    metric = payload.metric.value.replace("_", " ")
    value = f"{payload.value:g} {payload.unit}".strip()

    notified = await notify_family(
        session,
        family_id=senior.family_id,
        exclude_user_ids=[user.id],
        dedupe_prefix=f"device-flag:{flag_id}",
        template=NotificationRequest(
            user_id=user.id,  # replaced per recipient
            type=NotificationType.FAMILY_UPDATE,
            title=f"{senior.preferred_name}: {device} flagged a reading",
            body=(
                f"{metric.capitalize()} {value} — {payload.reason} "
                "Gamira has not assessed this reading."
            ),
            senior_profile_id=senior.id,
            related_entity_type="health_reading",
            related_entity_id=payload.reading_id,
        ),
    )
    await session.flush()

    check = await wellbeing_service.open_check(
        session,
        senior=senior,
        # The device's own sentence, unaltered. Gamira reads it out as
        # something her watch said, never as something she has concluded.
        reason=f"{metric.capitalize()} {value} — {payload.reason}",
        metric=payload.metric.value,
        value=payload.value,
        unit=payload.unit,
        source_device=payload.source_device,
        now=raised_at,
    )

    await record_audit(
        session,
        action="device_flag.raised",
        actor_user_id=user.id,
        target_type="senior_profile",
        target_id=senior.id,
        family_id=senior.family_id,
        metadata={
            "metric": payload.metric.value,
            "notified": len(notified),
            "wellbeing_check_id": str(check.id),
        },
    )
    publish_family_event(
        senior.family_id, "device_flag_raised", entity_type="notification"
    )

    return DeviceFlagOut(
        id=flag_id,
        senior_profile_id=senior.id,
        senior_name=senior.preferred_name,
        metric=payload.metric,
        value=payload.value,
        unit=payload.unit,
        reason=payload.reason,
        raised_at=raised_at,
        notified_user_ids=notified,
    )
