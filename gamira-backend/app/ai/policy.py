"""The policy engine.

Deliberately separate from the model, and deliberately ignorant of it. It takes
a tool name, arguments that have already been schema-checked, and the *verified*
actor — never a role, family id or senior id that appeared in a conversation —
and returns one of three verdicts.

It runs at execution time, not at session-creation time. That is the point: a
membership revoked while somebody is mid-conversation stops the next tool call,
even though the Live session was authorised minutes earlier and the model has
no idea anything changed.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools import ToolSpec
from app.db.base import utcnow
from app.models.enums import (
    MembershipRole,
    MembershipStatus,
    PolicyResult,
    UserStatus,
)
from app.models.identity import FamilyMembership, SeniorProfile, User
from app.services.authz import WRITE_ROLES

# Stable codes. Clients and the Live tool-response path switch on these; they
# are part of the contract, not log strings.
DENY_USER_SUSPENDED = "user_suspended"
DENY_MEMBERSHIP_REVOKED = "membership_revoked"
DENY_ROLE_INSUFFICIENT = "role_insufficient"
DENY_ENTITY_NOT_OWNED = "entity_not_owned"
DENY_TOOL_NOT_IN_SESSION = "tool_not_in_session"
DENY_UNKNOWN_TOOL = "unknown_tool"


@dataclass(frozen=True)
class ActorContext:
    """Who is actually asking, resolved from authentication and the database."""

    user: User
    senior: SeniorProfile
    membership: FamilyMembership

    @property
    def is_self(self) -> bool:
        """Is the caller the cared-for person, acting on their own record?"""
        return self.senior.user_id is not None and self.senior.user_id == self.user.id

    @property
    def has_write_role(self) -> bool:
        return self.membership.role in WRITE_ROLES


@dataclass(frozen=True)
class PolicyDecision:
    result: PolicyResult
    reason_code: str | None = None
    # The exact sentence a person is shown and hears. Built here rather than by
    # the model so what is confirmed and what is executed cannot differ.
    confirmation_prompt: str | None = None

    @property
    def allowed(self) -> bool:
        return self.result is PolicyResult.ALLOWED

    @property
    def needs_confirmation(self) -> bool:
        return self.result is PolicyResult.CONFIRMATION_REQUIRED


async def load_actor_context(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    senior_profile_id: uuid.UUID,
) -> ActorContext | None:
    """Re-read the actor from the database. Returns None when access is gone.

    Everything here is loaded fresh on every call. Caching it on the session
    row would be exactly the bug this function exists to prevent.
    """
    user = await session.get(User, user_id)
    senior = await session.get(SeniorProfile, senior_profile_id)
    if user is None or senior is None:
        return None
    membership = (
        await session.execute(
            select(FamilyMembership).where(
                FamilyMembership.user_id == user_id,
                FamilyMembership.family_id == senior.family_id,
                FamilyMembership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return None
    return ActorContext(user=user, senior=senior, membership=membership)


def evaluate(
    *,
    spec: ToolSpec,
    actor: ActorContext | None,
    in_session_snapshot: bool,
    confirmation_prompt: str | None = None,
    requires_confirmation: bool | None = None,
) -> PolicyDecision:
    """The verdict for one tool call. Pure, and testable on its own.

    ``requires_confirmation`` overrides the spec's own flag for this one call.
    The caller works it out with ``tools.needs_confirmation``, which is the only
    thing that reads the arguments — this function stays ignorant of them, and
    of the model that produced them. Omitting it keeps the spec's answer, so a
    tool that always confirms cannot be talked out of it from here.
    """
    if not in_session_snapshot:
        # The session never declared this tool. Even a legitimate tool added to
        # the server since is not callable here.
        return PolicyDecision(PolicyResult.DENIED, DENY_TOOL_NOT_IN_SESSION)

    if actor is None:
        return PolicyDecision(PolicyResult.DENIED, DENY_MEMBERSHIP_REVOKED)
    if actor.user.status is not UserStatus.ACTIVE:
        return PolicyDecision(PolicyResult.DENIED, DENY_USER_SUSPENDED)
    if actor.membership.status is not MembershipStatus.ACTIVE:
        return PolicyDecision(PolicyResult.DENIED, DENY_MEMBERSHIP_REVOKED)

    if spec.min_role is not None and not _satisfies(actor.membership.role, spec.min_role):
        return PolicyDecision(PolicyResult.DENIED, DENY_ROLE_INSUFFICIENT)

    if spec.kind == "mutation" and not (
        actor.has_write_role or (spec.self_allowed and actor.is_self)
    ):
        # A viewer who is not this person cannot record their doses by voice,
        # exactly as they cannot through the ordinary endpoint.
        return PolicyDecision(PolicyResult.DENIED, DENY_ROLE_INSUFFICIENT)

    confirm = (
        spec.requires_confirmation
        if requires_confirmation is None
        else requires_confirmation
    )
    if confirm:
        return PolicyDecision(
            PolicyResult.CONFIRMATION_REQUIRED,
            "confirmation_required",
            confirmation_prompt=confirmation_prompt,
        )
    return PolicyDecision(PolicyResult.ALLOWED)


def _satisfies(role: MembershipRole, minimum: MembershipRole) -> bool:
    from app.services.authz import ROLE_RANK

    return ROLE_RANK[role] >= ROLE_RANK[minimum]


def confirmation_deadline(seconds: int, now: dt.datetime | None = None) -> dt.datetime:
    return (now or utcnow()) + dt.timedelta(seconds=seconds)


__all__ = [
    "DENY_ENTITY_NOT_OWNED",
    "DENY_MEMBERSHIP_REVOKED",
    "DENY_ROLE_INSUFFICIENT",
    "DENY_TOOL_NOT_IN_SESSION",
    "DENY_UNKNOWN_TOOL",
    "DENY_USER_SUSPENDED",
    "ActorContext",
    "PolicyDecision",
    "confirmation_deadline",
    "evaluate",
    "load_actor_context",
]
