"""Users, families, memberships, senior profiles and invitations.

Access to any family data is derived from an active ``FamilyMembership``. No
table stores a role that a client can assert for itself.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Date,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import UtcDateTime
from app.models.enums import (
    ConsentStatus,
    FamilyStatus,
    InvitationStatus,
    MembershipRole,
    MembershipStatus,
    UserStatus,
)


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    # The identity provider's subject. Email and phone are contact details that
    # can change, so they are never used as the join key.
    external_auth_id: Mapped[str] = mapped_column(String(128), unique=True)
    auth_provider: Mapped[str] = mapped_column(String(32), default="firebase")
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    locale: Mapped[str] = mapped_column(String(16), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    theme: Mapped[str] = mapped_column(String(16), default="system")
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, length=16), default=UserStatus.ACTIVE
    )
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    memberships: Mapped[list[FamilyMembership]] = relationship(
        back_populates="user",
        foreign_keys="FamilyMembership.user_id",
        lazy="selectin",
    )


class Family(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "families"

    name: Mapped[str] = mapped_column(String(120))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[FamilyStatus] = mapped_column(
        Enum(FamilyStatus, native_enum=False, length=16), default=FamilyStatus.ACTIVE
    )

    memberships: Mapped[list[FamilyMembership]] = relationship(
        back_populates="family", foreign_keys="FamilyMembership.family_id"
    )
    seniors: Mapped[list[SeniorProfile]] = relationship(back_populates="family")


class FamilyMembership(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "family_memberships"
    __table_args__ = (
        # A user may hold at most one non-revoked membership per family; history
        # is preserved by keeping revoked rows.
        #
        # The predicate matches `MembershipStatus.REVOKED.name` ("REVOKED"), not
        # `.value` ("revoked"): `Enum(..., native_enum=False)` with no
        # `values_callable` stores a Python enum's *name*, not its value — the
        # ORM round-trips this transparently, but a hand-written predicate has
        # to know it. Confirmed against a real PostgreSQL server: the lowercase
        # form silently never matched any row, so this partial index never
        # actually rejected a second live membership.
        Index(
            "uq_family_memberships_family_user_live",
            "family_id",
            "user_id",
            unique=True,
            sqlite_where=text(f"status <> '{MembershipStatus.REVOKED.name}'"),
            postgresql_where=text(f"status <> '{MembershipStatus.REVOKED.name}'"),
        ),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, native_enum=False, length=16)
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, length=16),
        default=MembershipStatus.ACTIVE,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    family: Mapped[Family] = relationship(
        back_populates="memberships", foreign_keys=[family_id]
    )
    user: Mapped[User] = relationship(
        back_populates="memberships", foreign_keys=[user_id]
    )


class SeniorProfile(UUIDPrimaryKey, Timestamps, Base):
    """The cared-for person. The Family Dashboard calls this a family member."""

    __tablename__ = "senior_profiles"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    # Set once the senior signs in to the Parent App themselves.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    preferred_name: Mapped[str] = mapped_column(String(120))
    relationship_label: Mapped[str | None] = mapped_column(String(64))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    phone: Mapped[str | None] = mapped_column(String(32))
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date())
    gender: Mapped[str | None] = mapped_column(String(16))
    blood_group: Mapped[str | None] = mapped_column(String(8))
    # Care context a responder or family member may need at a glance. Gamira
    # stores what a person or their family recorded; it does not diagnose.
    conditions: Mapped[list | None] = mapped_column(JSON())
    allergies: Mapped[list | None] = mapped_column(JSON())
    notes: Mapped[str | None] = mapped_column(Text())
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    language: Mapped[str] = mapped_column(String(16), default="en")
    consent_status: Mapped[ConsentStatus] = mapped_column(
        Enum(ConsentStatus, native_enum=False, length=24),
        default=ConsentStatus.NOT_REQUESTED,
    )
    consent_recorded_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    consent_recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id")
    )
    archived_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    family: Mapped[Family] = relationship(back_populates="seniors")


class FamilyInvitation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "family_invitations"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, native_enum=False, length=16)
    )
    # Set only when this invitation is how a cared-for person links their own
    # sign-in to their existing profile, rather than adding a new caregiver.
    senior_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    # Only the hash is stored; the raw token is returned once, at creation.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_email: Mapped[str | None] = mapped_column(String(320))
    invited_phone: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, native_enum=False, length=16),
        default=InvitationStatus.PENDING,
    )
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    accepted_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())


__all__ = [
    "Family",
    "FamilyInvitation",
    "FamilyMembership",
    "SeniorProfile",
    "User",
]
