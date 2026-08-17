"""Request and response models for users, families and seniors."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import ConsentStatus, MembershipRole, MembershipStatus
from app.schemas.common import ApiModel
from app.services.scheduling import load_timezone


def _validate_timezone(value: str) -> str:
    load_timezone(value)
    return value


class UserOut(ApiModel):
    id: uuid.UUID
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    locale: str
    timezone: str
    theme: str


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1024)
    locale: str | None = Field(default=None, max_length=16)
    timezone: str | None = None
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value else value


class MembershipOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    user_id: uuid.UUID
    role: MembershipRole
    status: MembershipStatus
    accepted_at: dt.datetime | None = None


class MemberOut(ApiModel):
    """A membership joined with the person behind it, for the members list."""

    id: uuid.UUID
    family_id: uuid.UUID
    user_id: uuid.UUID
    role: MembershipRole
    status: MembershipStatus
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None


class FamilyOut(ApiModel):
    id: uuid.UUID
    name: str
    created_by_user_id: uuid.UUID


class FamilyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class FamilyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class MeOut(BaseModel):
    """Everything a client needs to render the signed-in session."""

    user: UserOut
    families: list[FamilyOut]
    memberships: list[MembershipOut]
    seniors: list[SeniorOut]


class InvitationCreate(BaseModel):
    role: MembershipRole = MembershipRole.FAMILY
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)


class InvitationOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    role: MembershipRole
    invited_email: str | None = None
    expires_at: dt.datetime


class InvitationCreated(BaseModel):
    """The raw token is returned once, at creation, and never stored or logged."""

    invitation: InvitationOut
    token: str


class SeniorCreate(BaseModel):
    preferred_name: str = Field(min_length=1, max_length=120)
    relationship_label: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=1024)
    date_of_birth: dt.date | None = None
    gender: str | None = Field(default=None, max_length=16)
    blood_group: str | None = Field(default=None, max_length=8)
    conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    notes: str | None = None
    timezone: str = "Asia/Kolkata"
    language: str = "en"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        return _validate_timezone(value)


class SeniorUpdate(BaseModel):
    preferred_name: str | None = Field(default=None, min_length=1, max_length=120)
    relationship_label: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=1024)
    date_of_birth: dt.date | None = None
    gender: str | None = Field(default=None, max_length=16)
    blood_group: str | None = Field(default=None, max_length=8)
    conditions: list[str] | None = None
    allergies: list[str] | None = None
    notes: str | None = None
    timezone: str | None = None
    language: str | None = Field(default=None, max_length=16)
    consent_status: ConsentStatus | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value else value


class SeniorOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    user_id: uuid.UUID | None = None
    preferred_name: str
    relationship_label: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    date_of_birth: dt.date | None = None
    gender: str | None = None
    blood_group: str | None = None
    conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    notes: str | None = None
    timezone: str
    language: str
    consent_status: ConsentStatus

    @field_validator("conditions", "allergies", mode="before")
    @classmethod
    def _empty_list(cls, value: list[str] | None) -> list[str]:
        # These columns are nullable, and a missing list reads as "none
        # recorded" rather than as an error.
        return value or []


MeOut.model_rebuild()
