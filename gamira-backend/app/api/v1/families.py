"""Families, members, invitations and senior profiles."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.models.enums import (
    ConsentStatus,
    MembershipRole,
    MembershipStatus,
    TimelineEventType,
)
from app.models.identity import Family, FamilyMembership, SeniorProfile, User
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

    invitation, raw_token = await identity_service.create_invitation(
        session,
        family_id=family_id,
        invited_by=user,
        role=payload.role,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
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
    token: str, session: SessionDep, user: CurrentUser
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
