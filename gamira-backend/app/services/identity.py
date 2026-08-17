"""User provisioning, family creation and invitations."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.security import VerifiedIdentity
from app.db.base import utcnow
from app.models.enums import (
    InvitationStatus,
    MembershipRole,
    MembershipStatus,
)
from app.models.identity import Family, FamilyInvitation, FamilyMembership, User

INVITATION_TTL = dt.timedelta(days=7)


async def get_or_create_user(session: AsyncSession, identity: VerifiedIdentity) -> User:
    """Map a verified external identity onto the internal user record.

    Contact details are refreshed from the provider, but never used to match an
    existing row — only ``external_auth_id`` identifies a user.
    """
    result = await session.execute(
        select(User).where(User.external_auth_id == identity.external_auth_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            external_auth_id=identity.external_auth_id,
            auth_provider=identity.provider,
            email=identity.email,
            phone=identity.phone,
            display_name=identity.display_name or _default_name(identity),
            avatar_url=identity.picture,
        )
        session.add(user)
        await session.flush()
        return user

    if identity.email and user.email != identity.email:
        user.email = identity.email
    if identity.phone and user.phone != identity.phone:
        user.phone = identity.phone
    if identity.display_name and not user.display_name:
        user.display_name = identity.display_name
    user.last_seen_at = utcnow()
    return user


def _default_name(identity: VerifiedIdentity) -> str:
    if identity.email:
        return identity.email.split("@", 1)[0]
    return "Gamira user"


async def create_family(session: AsyncSession, *, owner: User, name: str) -> Family:
    family = Family(name=name.strip(), created_by_user_id=owner.id)
    session.add(family)
    await session.flush()
    session.add(
        FamilyMembership(
            family_id=family.id,
            user_id=owner.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            accepted_at=utcnow(),
        )
    )
    await session.flush()
    return family


def hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def create_invitation(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    invited_by: User,
    role: MembershipRole,
    email: str | None = None,
    phone: str | None = None,
) -> tuple[FamilyInvitation, str]:
    """Create an invitation and return it with its one-time raw token.

    The raw token is returned to the caller exactly once; only its hash is
    persisted, so a database read cannot be replayed as an acceptance.
    """
    raw_token = secrets.token_urlsafe(32)
    invitation = FamilyInvitation(
        family_id=family_id,
        invited_by_user_id=invited_by.id,
        role=role,
        token_hash=hash_invitation_token(raw_token),
        invited_email=email,
        invited_phone=phone,
        expires_at=utcnow() + INVITATION_TTL,
    )
    session.add(invitation)
    await session.flush()
    return invitation, raw_token


async def accept_invitation(
    session: AsyncSession, *, raw_token: str, user: User
) -> FamilyMembership:
    result = await session.execute(
        select(FamilyInvitation).where(
            FamilyInvitation.token_hash == hash_invitation_token(raw_token)
        )
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise NotFound("This invitation link is not valid.")
    if invitation.status is not InvitationStatus.PENDING:
        raise Conflict(
            "This invitation has already been used or revoked.",
            code="invitation_not_pending",
        )
    if invitation.expires_at <= utcnow():
        invitation.status = InvitationStatus.EXPIRED
        raise Conflict("This invitation has expired.", code="invitation_expired")

    existing = await session.execute(
        select(FamilyMembership).where(
            FamilyMembership.family_id == invitation.family_id,
            FamilyMembership.user_id == user.id,
            FamilyMembership.status != MembershipStatus.REVOKED,
        )
    )
    membership = existing.scalar_one_or_none()
    if membership is None:
        membership = FamilyMembership(
            family_id=invitation.family_id,
            user_id=user.id,
            role=invitation.role,
            status=MembershipStatus.ACTIVE,
            invited_by_user_id=invitation.invited_by_user_id,
            accepted_at=utcnow(),
        )
        session.add(membership)
    else:
        membership.status = MembershipStatus.ACTIVE
        membership.accepted_at = utcnow()

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = utcnow()
    invitation.accepted_by_user_id = user.id
    await session.flush()
    return membership


async def revoke_membership(
    session: AsyncSession, *, membership: FamilyMembership
) -> FamilyMembership:
    if membership.role is MembershipRole.OWNER:
        owners = await session.execute(
            select(FamilyMembership).where(
                FamilyMembership.family_id == membership.family_id,
                FamilyMembership.role == MembershipRole.OWNER,
                FamilyMembership.status == MembershipStatus.ACTIVE,
            )
        )
        if len(owners.scalars().all()) <= 1:
            raise Conflict(
                "A family must keep at least one owner.",
                code="last_owner_cannot_be_removed",
            )
    membership.status = MembershipStatus.REVOKED
    membership.revoked_at = utcnow()
    await session.flush()
    return membership
