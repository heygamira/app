"""Server-side authorization.

Every read and write goes through one of these helpers. A client never states
its own family, role or entitlement; the membership row is the only source.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
from app.models.enums import MembershipRole, MembershipStatus
from app.models.identity import Family, FamilyMembership, SeniorProfile

# Ordered from most to least privileged. A role satisfies a requirement when its
# rank is at or above the required role's rank.
ROLE_RANK: dict[MembershipRole, int] = {
    MembershipRole.OWNER: 40,
    MembershipRole.CAREGIVER: 30,
    MembershipRole.FAMILY: 20,
    MembershipRole.DOCTOR: 10,
    MembershipRole.VIEWER: 0,
}

# Roles allowed to change care data. Doctors and viewers read only.
WRITE_ROLES: frozenset[MembershipRole] = frozenset(
    {MembershipRole.OWNER, MembershipRole.CAREGIVER, MembershipRole.FAMILY}
)


async def active_memberships(
    session: AsyncSession, user_id: uuid.UUID
) -> Sequence[FamilyMembership]:
    result = await session.execute(
        select(FamilyMembership).where(
            FamilyMembership.user_id == user_id,
            FamilyMembership.status == MembershipStatus.ACTIVE,
        )
    )
    return result.scalars().all()


async def require_membership(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    minimum_role: MembershipRole = MembershipRole.VIEWER,
) -> FamilyMembership:
    result = await session.execute(
        select(FamilyMembership).where(
            FamilyMembership.user_id == user_id,
            FamilyMembership.family_id == family_id,
            FamilyMembership.status == MembershipStatus.ACTIVE,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        # Deliberately the same answer as "no such family": a caller outside the
        # family must not be able to probe which family ids exist.
        raise NotFound("The requested resource does not exist.")
    if ROLE_RANK[membership.role] < ROLE_RANK[minimum_role]:
        raise PermissionDenied(
            "Your role in this family does not allow this action.",
            details={"required_role": minimum_role.value, "role": membership.role.value},
        )
    return membership


async def require_write_access(
    session: AsyncSession, *, user_id: uuid.UUID, family_id: uuid.UUID
) -> FamilyMembership:
    membership = await require_membership(session, user_id=user_id, family_id=family_id)
    if membership.role not in WRITE_ROLES:
        raise PermissionDenied("Your role in this family is read-only.")
    return membership


async def require_self_or_write_access(
    session: AsyncSession, *, user_id: uuid.UUID, senior_profile_id: uuid.UUID
) -> FamilyMembership:
    """Allow the cared-for person to act on their own record.

    A senior is typically a viewer in their family: they are not there to
    administer other people's care. But the Parent App is their own device, and
    confirming their own dose is the one thing they must always be able to do.
    Anyone else still needs a write role.
    """
    senior = await session.get(SeniorProfile, senior_profile_id)
    if senior is None:
        raise NotFound("The requested person does not exist.")

    membership = await require_membership(
        session, user_id=user_id, family_id=senior.family_id
    )
    if senior.user_id == user_id:
        return membership
    if membership.role not in WRITE_ROLES:
        raise PermissionDenied("Your role in this family is read-only.")
    return membership


async def get_family(session: AsyncSession, family_id: uuid.UUID) -> Family:
    family = await session.get(Family, family_id)
    if family is None:
        raise NotFound("The requested family does not exist.")
    return family


async def resolve_senior(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    senior_id: uuid.UUID,
    write: bool = False,
) -> tuple[SeniorProfile, FamilyMembership]:
    """Load a senior profile only if the caller has access to its family."""
    senior = await session.get(SeniorProfile, senior_id)
    if senior is None:
        raise NotFound("The requested person does not exist.")
    if write:
        membership = await require_write_access(
            session, user_id=user_id, family_id=senior.family_id
        )
    else:
        membership = await require_membership(
            session, user_id=user_id, family_id=senior.family_id
        )
    return senior, membership
