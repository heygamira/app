"""Families, members, invitations and senior profiles."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.api.rate_limit import rate_limit
from app.api.v1.medications import _dose_out, _resolve_window
from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.models.care import Appointment, HealthReading, Reminder, TimelineEvent
from app.models.enums import (
    ConsentStatus,
    MedicationStatus,
    MembershipRole,
    MembershipStatus,
    ReminderStatus,
    TimelineEventType,
)
from app.models.identity import Family, FamilyMembership, SeniorProfile, User
from app.models.medication import DoseEvent, Medication
from app.schemas.care import (
    AppointmentOut,
    DashboardSummaryOut,
    HealthReadingOut,
    ReminderOut,
    TimelineEventOut,
)
from app.schemas.identity import (
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
    MemberOut,
    SeniorCreate,
    SeniorOut,
    SeniorUpdate,
)
from app.schemas.medication import DoseEventOut, MedicationOut
from app.services import identity as identity_service
from app.services.authz import (
    require_membership,
    require_write_access,
    resolve_senior,
)
from app.services.timeline import record_audit, record_timeline_event

router = APIRouter(tags=["families"])


@router.post("/families", response_model=FamilyOut, status_code=status.HTTP_201_CREATED)
async def create_family(
    payload: FamilyCreate, session: SessionDep, user: CurrentUser
) -> FamilyOut:
    family = await identity_service.create_family(session, owner=user, name=payload.name)
    await record_audit(
        session,
        action="family.create",
        actor_user_id=user.id,
        target_type="family",
        target_id=family.id,
        family_id=family.id,
    )
    return FamilyOut.model_validate(family)


@router.get("/families/{family_id}", response_model=FamilyOut)
async def get_family(
    family_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> FamilyOut:
    await require_membership(session, user_id=user.id, family_id=family_id)
    family = await session.get(Family, family_id)
    if family is None:
        raise NotFound("The requested family does not exist.")
    return FamilyOut.model_validate(family)


@router.patch("/families/{family_id}", response_model=FamilyOut)
async def update_family(
    family_id: uuid.UUID,
    payload: FamilyUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> FamilyOut:
    await require_membership(
        session, user_id=user.id, family_id=family_id, minimum_role=MembershipRole.OWNER
    )
    family = await session.get(Family, family_id)
    if family is None:
        raise NotFound("The requested family does not exist.")
    if payload.name:
        family.name = payload.name
    await session.flush()
    return FamilyOut.model_validate(family)


@router.get("/families/{family_id}/members", response_model=list[MemberOut])
async def list_members(
    family_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[MemberOut]:
    await require_membership(session, user_id=user.id, family_id=family_id)
    rows = await session.execute(
        select(FamilyMembership, User)
        .join(User, User.id == FamilyMembership.user_id)
        .where(
            FamilyMembership.family_id == family_id,
            FamilyMembership.status != MembershipStatus.REVOKED,
        )
        .order_by(FamilyMembership.created_at)
    )
    return [
        MemberOut(
            id=membership.id,
            family_id=membership.family_id,
            user_id=membership.user_id,
            role=membership.role,
            status=membership.status,
            display_name=member.display_name,
            email=member.email,
            avatar_url=member.avatar_url,
        )
        for membership, member in rows.all()
    ]


@router.post(
    "/families/{family_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    family_id: uuid.UUID,
    payload: InvitationCreate,
    session: SessionDep,
    user: CurrentUser,
    _rate_limit: Annotated[
        None, rate_limit("invitation_create", limit=20, window_seconds=3600)
    ],
) -> InvitationCreated:
    """Issue an invitation. Only an owner may grant the owner role."""
    membership = await require_membership(
        session,
        user_id=user.id,
        family_id=family_id,
        minimum_role=MembershipRole.CAREGIVER,
    )
    if (
        payload.role is MembershipRole.OWNER
        and membership.role is not MembershipRole.OWNER
    ):
        raise Conflict(
            "Only an owner can invite another owner.", code="owner_invite_forbidden"
        )

    role = payload.role
    if payload.senior_profile_id is not None:
        senior = await session.get(SeniorProfile, payload.senior_profile_id)
        if senior is None or senior.family_id != family_id:
            raise NotFound("The requested person does not exist.")
        if senior.user_id is not None:
            raise Conflict(
                "This person's profile is already linked to an account.",
                code="senior_already_linked",
            )
        # A senior is a viewer of their own family record, never invited in
        # with a caregiver's authority over it.
        role = MembershipRole.VIEWER

    invitation, raw_token = await identity_service.create_invitation(
        session,
        family_id=family_id,
        invited_by=user,
        role=role,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        senior_profile_id=payload.senior_profile_id,
    )
    await record_audit(
        session,
        action="family.invitation.create",
        actor_user_id=user.id,
        target_type="family_invitation",
        target_id=invitation.id,
        family_id=family_id,
        metadata={"role": payload.role.value},
    )
    return InvitationCreated(
        invitation=InvitationOut.model_validate(invitation), token=raw_token
    )


@router.post("/invitations/{token}/accept", response_model=MemberOut)
async def accept_invitation(
    token: str,
    session: SessionDep,
    user: CurrentUser,
    _rate_limit: Annotated[
        None, rate_limit("invitation_accept", limit=20, window_seconds=3600)
    ],
) -> MemberOut:
    membership = await identity_service.accept_invitation(
        session, raw_token=token, user=user
    )
    await record_audit(
        session,
        action="family.invitation.accept",
        actor_user_id=user.id,
        target_type="family_membership",
        target_id=membership.id,
        family_id=membership.family_id,
    )
    return MemberOut(
        id=membership.id,
        family_id=membership.family_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        display_name=user.display_name,
        email=user.email,
        avatar_url=user.avatar_url,
    )


@router.delete(
    "/families/{family_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_member(
    family_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> None:
    await require_membership(
        session, user_id=user.id, family_id=family_id, minimum_role=MembershipRole.OWNER
    )
    membership = await session.get(FamilyMembership, membership_id)
    if membership is None or membership.family_id != family_id:
        raise NotFound("The requested membership does not exist.")
    await identity_service.revoke_membership(session, membership=membership)
    await record_audit(
        session,
        action="family.membership.revoke",
        actor_user_id=user.id,
        target_type="family_membership",
        target_id=membership.id,
        family_id=family_id,
    )


@router.get("/families/{family_id}/seniors", response_model=list[SeniorOut])
async def list_seniors(
    family_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[SeniorOut]:
    await require_membership(session, user_id=user.id, family_id=family_id)
    rows = await session.execute(
        select(SeniorProfile)
        .where(
            SeniorProfile.family_id == family_id,
            SeniorProfile.archived_at.is_(None),
        )
        .order_by(SeniorProfile.created_at)
    )
    return [SeniorOut.model_validate(row) for row in rows.scalars()]


@router.post(
    "/families/{family_id}/seniors",
    response_model=SeniorOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_senior(
    family_id: uuid.UUID,
    payload: SeniorCreate,
    session: SessionDep,
    user: CurrentUser,
) -> SeniorOut:
    """Add a cared-for person.

    Consent starts as ``pending``: a family member creating the profile is not
    the same thing as the senior agreeing to be monitored.
    """
    await require_write_access(session, user_id=user.id, family_id=family_id)
    senior = SeniorProfile(
        family_id=family_id,
        consent_status=ConsentStatus.PENDING,
        **payload.model_dump(),
    )
    session.add(senior)
    await session.flush()

    await record_timeline_event(
        session,
        family_id=family_id,
        senior_profile_id=senior.id,
        type=TimelineEventType.MEMBER_JOINED,
        title=f"{senior.preferred_name} added to the family",
        actor_user_id=user.id,
    )
    await record_audit(
        session,
        action="senior.create",
        actor_user_id=user.id,
        target_type="senior_profile",
        target_id=senior.id,
        family_id=family_id,
    )
    return SeniorOut.model_validate(senior)


@router.get("/seniors/{senior_id}", response_model=SeniorOut)
async def get_senior(
    senior_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> SeniorOut:
    senior, _ = await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    return SeniorOut.model_validate(senior)


@router.patch("/seniors/{senior_id}", response_model=SeniorOut)
async def update_senior(
    senior_id: uuid.UUID,
    payload: SeniorUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> SeniorOut:
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=senior_id, write=True
    )
    changes = payload.model_dump(exclude_unset=True)
    consent = changes.pop("consent_status", None)
    for field, value in changes.items():
        setattr(senior, field, value)
    if consent is not None:
        senior.consent_status = consent
        senior.consent_recorded_at = utcnow()
        senior.consent_recorded_by_user_id = user.id
        await record_audit(
            session,
            action="senior.consent.update",
            actor_user_id=user.id,
            target_type="senior_profile",
            target_id=senior.id,
            family_id=senior.family_id,
            metadata={"consent_status": str(consent)},
        )
    await session.flush()
    return SeniorOut.model_validate(senior)


@router.delete(
    "/seniors/{senior_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def archive_senior(
    senior_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    """Archive rather than delete: medication and alert history must survive."""
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=senior_id, write=True
    )
    senior.archived_at = utcnow()
    await session.flush()
    await record_audit(
        session,
        action="senior.archive",
        actor_user_id=user.id,
        target_type="senior_profile",
        target_id=senior.id,
        family_id=senior.family_id,
    )


@router.get(
    "/families/{family_id}/dashboard-summary", response_model=DashboardSummaryOut
)
async def dashboard_summary(
    family_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DashboardSummaryOut:
    """Everything the dashboard's Home screen shows, for every senior in the
    family, in one request.

    Replaces the fan-out the frontend used to do itself: six requests per
    senior shown (`...ForMembers` in the dashboard's own dashboardData.js),
    every poll tick, so a three-senior family cost eighteen requests every
    five seconds from one open tab. Every model here already carries
    `family_id`, so each list below is one indexed query — except doses,
    which stay one query per senior because "today" is resolved in that
    senior's own timezone, exactly as the single-senior route does.
    """
    await require_membership(session, user_id=user.id, family_id=family_id)

    senior_rows = await session.execute(
        select(SeniorProfile)
        .where(
            SeniorProfile.family_id == family_id,
            SeniorProfile.archived_at.is_(None),
        )
        .order_by(SeniorProfile.created_at)
    )
    seniors = list(senior_rows.scalars())
    # How many seniors' worth of "recent" is still recent for the family as a
    # whole — bounding the family-wide feeds without reintroducing a per-senior
    # request for each of them.
    fan_out = max(1, len(seniors))

    doses: list[DoseEventOut] = []
    for senior in seniors:
        window_start, window_end = _resolve_window(senior.timezone, None, None)
        rows = await session.execute(
            select(DoseEvent)
            .options(
                selectinload(DoseEvent.medication), selectinload(DoseEvent.schedule)
            )
            .where(
                DoseEvent.senior_profile_id == senior.id,
                DoseEvent.scheduled_at_utc >= window_start,
                DoseEvent.scheduled_at_utc < window_end,
            )
            .order_by(DoseEvent.scheduled_at_utc)
        )
        doses.extend(_dose_out(event) for event in rows.scalars().unique())

    health_rows = await session.execute(
        select(HealthReading)
        .where(HealthReading.family_id == family_id)
        .order_by(HealthReading.measured_at.desc())
        .limit(min(200, 40 * fan_out))
    )
    health_readings = [
        HealthReadingOut.model_validate(row) for row in health_rows.scalars()
    ]

    medication_rows = await session.execute(
        select(Medication)
        .options(selectinload(Medication.schedules))
        .where(
            Medication.family_id == family_id,
            Medication.status != MedicationStatus.ARCHIVED,
        )
        .order_by(Medication.created_at.desc())
    )
    medications = [
        MedicationOut.model_validate(row) for row in medication_rows.scalars().unique()
    ]

    timeline_rows = await session.execute(
        select(TimelineEvent)
        .where(TimelineEvent.family_id == family_id)
        .order_by(TimelineEvent.occurred_at.desc())
        .limit(min(150, 30 * fan_out))
    )
    timeline = [TimelineEventOut.model_validate(row) for row in timeline_rows.scalars()]

    appointment_rows = await session.execute(
        select(Appointment)
        .where(Appointment.family_id == family_id)
        .order_by(Appointment.starts_at.desc())
    )
    appointments = [
        AppointmentOut.model_validate(row) for row in appointment_rows.scalars()
    ]

    reminder_rows = await session.execute(
        select(Reminder)
        .where(
            Reminder.family_id == family_id, Reminder.status != ReminderStatus.ARCHIVED
        )
        .order_by(Reminder.local_time.nulls_last(), Reminder.created_at)
    )
    reminders = [ReminderOut.model_validate(row) for row in reminder_rows.scalars()]

    return DashboardSummaryOut(
        seniors=[SeniorOut.model_validate(senior) for senior in seniors],
        doses=doses,
        health_readings=health_readings,
        medications=medications,
        timeline=timeline,
        appointments=appointments,
        reminders=reminders,
    )
