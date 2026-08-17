"""The signed-in session: user, families, memberships and visible seniors."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.models.identity import Family, SeniorProfile
from app.schemas.identity import (
    FamilyOut,
    MembershipOut,
    MeOut,
    SeniorOut,
    UserOut,
    UserUpdate,
)
from app.services.authz import active_memberships

router = APIRouter(tags=["session"])


async def _build_me(session: SessionDep, user: CurrentUser) -> MeOut:
    memberships = await active_memberships(session, user.id)
    family_ids = [membership.family_id for membership in memberships]

    families: list[Family] = []
    seniors: list[SeniorProfile] = []
    if family_ids:
        families = list(
            (
                await session.execute(select(Family).where(Family.id.in_(family_ids)))
            ).scalars()
        )
        seniors = list(
            (
                await session.execute(
                    select(SeniorProfile)
                    .where(
                        SeniorProfile.family_id.in_(family_ids),
                        SeniorProfile.archived_at.is_(None),
                    )
                    .order_by(SeniorProfile.created_at)
                )
            ).scalars()
        )

    return MeOut(
        user=UserOut.model_validate(user),
        families=[FamilyOut.model_validate(f) for f in families],
        memberships=[MembershipOut.model_validate(m) for m in memberships],
        seniors=[SeniorOut.model_validate(s) for s in seniors],
    )


@router.get("/me", response_model=MeOut)
async def read_me(session: SessionDep, user: CurrentUser) -> MeOut:
    return await _build_me(session, user)


@router.patch("/me", response_model=MeOut)
async def update_me(payload: UserUpdate, session: SessionDep, user: CurrentUser) -> MeOut:
    """Update the caller's own profile only. Role and status are not writable."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    await session.flush()
    return await _build_me(session, user)
