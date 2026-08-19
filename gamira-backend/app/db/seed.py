"""Development seed data.

Two unrelated families are created on purpose. Anything that can see across
them is an authorization bug, and the test suite asserts that it cannot.

All identities and measurements here are fictional. Run with::

    python -m app.db.seed [--reset]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import Base, utcnow
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.models.care import (
    EmergencyContact,
    HealthReading,
    NotificationDelivery,
    Reminder,
)
from app.models.enums import (
    ConsentStatus,
    HealthMetric,
    HealthSource,
    MembershipRole,
    MembershipStatus,
    NotificationType,
    ReminderType,
)
from app.models.identity import Family, FamilyMembership, SeniorProfile, User
from app.models.medication import Medication, MedicationSchedule

# Subjects match the dev bearer tokens: `dev:sharma-owner` signs in as Anjali.
SEED_USERS = [
    ("sharma-owner", "anjali.sharma@example.test", "Anjali Sharma"),
    ("sharma-caregiver", "rohan.sharma@example.test", "Rohan Sharma"),
    ("sharma-senior", "dadaji@example.test", "Vikram Sharma"),
    # A second cared-for person in the same family, with their own account, so
    # two Parent Apps can run side by side under one Family Dashboard.
    ("sharma-senior-2", "dadiji@example.test", "Sunita Sharma"),
    # A second family, unrelated to the Sharmas, with its own caregiver and
    # cared-for person — so multi-family switching and cross-family isolation
    # are actually exercisable locally rather than the family being an owner
    # signed in alone.
    ("iyer-owner", "meera.iyer@example.test", "Meera Iyer"),
    ("iyer-caregiver", "arjun.iyer@example.test", "Arjun Iyer"),
    ("iyer-senior", "lakshmi.iyer@example.test", "Lakshmi Iyer"),
    # Belongs to both families, so signing in as this person is the way to
    # exercise the dashboard's family switcher locally.
    ("dual-caregiver", "priya.rao@example.test", "Priya Rao"),
]


async def seed(reset: bool = False) -> None:
    settings = get_settings()
    if settings.app_env not in ("local", "test"):
        raise SystemExit(
            f"Refusing to seed a '{settings.app_env}' environment. "
            "Seed data is for local development only."
        )

    if reset:
        # Drop and recreate rather than deleting rows, so a changed schema does
        # not leave a half-migrated local database behind.
        engine = get_engine()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)

    async with get_sessionmaker()() as session:
        if await _already_seeded(session) and not reset:
            print("Seed data already present. Use --reset to rebuild it.")
            return
        await _create_seed_data(session)
        await session.commit()

    print(
        "Seeded two families (Sharma cares for two people; Priya Rao belongs "
        "to both, for testing the family switcher). Sign in with:"
    )
    for subject, email, name in SEED_USERS:
        print(f"  Authorization: Bearer dev:{subject}    ({name}, {email})")


async def _already_seeded(session: AsyncSession) -> bool:
    result = await session.execute(select(User.id).limit(1))
    return result.first() is not None


async def _create_seed_data(session: AsyncSession) -> None:
    users: dict[str, User] = {}
    for subject, email, name in SEED_USERS:
        user = User(
            external_auth_id=f"dev|{subject}",
            auth_provider="dev",
            email=email,
            display_name=name,
            timezone="Asia/Kolkata",
        )
        session.add(user)
        users[subject] = user
    await session.flush()

    sharma = await _build_family(
        session,
        name="Sharma family",
        owner=users["sharma-owner"],
        caregiver=users["sharma-caregiver"],
        senior_user=users["sharma-senior"],
        senior_name="Vikram Sharma",
        timezone="Asia/Kolkata",
    )
    iyer = await _build_family(
        session,
        name="Iyer family",
        owner=users["iyer-owner"],
        caregiver=users["iyer-caregiver"],
        senior_user=users["iyer-senior"],
        senior_name="Lakshmi Iyer",
        timezone="Asia/Kolkata",
    )

    sharma_family, vikram = sharma
    sunita = await _add_senior(
        session,
        family=sharma_family,
        senior_user=users["sharma-senior-2"],
        senior_name="Sunita Sharma",
        timezone="Asia/Kolkata",
        recorded_by=users["sharma-owner"],
    )

    await _add_care_data(session, family=sharma_family, senior=vikram)
    await _add_care_data(
        session, family=sharma_family, senior=sunita, medication_name="Metformin"
    )
    await _add_care_data(session, family=iyer[0], senior=iyer[1])

    dual = users["dual-caregiver"]
    session.add_all(
        [
            FamilyMembership(
                family_id=sharma_family.id,
                user_id=dual.id,
                role=MembershipRole.CAREGIVER,
                status=MembershipStatus.ACTIVE,
                invited_by_user_id=users["sharma-owner"].id,
                accepted_at=utcnow(),
            ),
            FamilyMembership(
                family_id=iyer[0].id,
                user_id=dual.id,
                role=MembershipRole.CAREGIVER,
                status=MembershipStatus.ACTIVE,
                invited_by_user_id=users["iyer-owner"].id,
                accepted_at=utcnow(),
            ),
        ]
    )

    session.add(
        NotificationDelivery(
            user_id=users["sharma-owner"].id,
            family_id=sharma[0].id,
            senior_profile_id=sharma[1].id,
            type=NotificationType.FAMILY_UPDATE,
            title="Vikram confirmed his morning dose",
            body="Recorded at 08:05 local time.",
            dedupe_key=f"seed-family-update-{sharma[1].id}",
        )
    )
    await session.flush()


async def _build_family(
    session: AsyncSession,
    *,
    name: str,
    owner: User,
    caregiver: User | None,
    senior_user: User | None,
    senior_name: str,
    timezone: str,
) -> tuple[Family, SeniorProfile]:
    family = Family(name=name, created_by_user_id=owner.id)
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
    if caregiver is not None:
        session.add(
            FamilyMembership(
                family_id=family.id,
                user_id=caregiver.id,
                role=MembershipRole.CAREGIVER,
                status=MembershipStatus.ACTIVE,
                invited_by_user_id=owner.id,
                accepted_at=utcnow(),
            )
        )

    senior = await _add_senior(
        session,
        family=family,
        senior_user=senior_user,
        senior_name=senior_name,
        timezone=timezone,
        recorded_by=owner,
    )
    return family, senior


async def _add_senior(
    session: AsyncSession,
    *,
    family: Family,
    senior_user: User | None,
    senior_name: str,
    timezone: str,
    recorded_by: User,
) -> SeniorProfile:
    """Add one cared-for person to an existing family.

    A family may care for more than one person. When that person has their own
    account they join as a viewer: the Parent App is their device, not a place
    to administer anyone else's care.
    """
    senior = SeniorProfile(
        family_id=family.id,
        user_id=senior_user.id if senior_user else None,
        preferred_name=senior_name,
        relationship_label="Parent",
        timezone=timezone,
        language="en",
        consent_status=ConsentStatus.GRANTED,
        consent_recorded_at=utcnow(),
        consent_recorded_by_user_id=recorded_by.id,
    )
    session.add(senior)
    await session.flush()

    if senior_user is not None:
        session.add(
            FamilyMembership(
                family_id=family.id,
                user_id=senior_user.id,
                role=MembershipRole.VIEWER,
                status=MembershipStatus.ACTIVE,
                accepted_at=utcnow(),
            )
        )
    await session.flush()
    return senior


async def _add_care_data(
    session: AsyncSession,
    *,
    family: Family,
    senior: SeniorProfile,
    medication_name: str = "Amlodipine",
) -> None:
    medication = Medication(
        family_id=family.id,
        senior_profile_id=senior.id,
        name=medication_name,
        form="tablet",
        strength="5 mg",
        instructions="Take with water after breakfast.",
        prescriber="Dr. Fictional",
        start_date=dt.date.today() - dt.timedelta(days=30),
        created_by_user_id=family.created_by_user_id,
    )
    session.add(medication)
    await session.flush()

    session.add_all(
        [
            MedicationSchedule(
                medication_id=medication.id,
                local_time="08:00",
                timezone=senior.timezone,
                dose_quantity="1 tablet",
                late_after_minutes=30,
                missed_after_minutes=120,
            ),
            MedicationSchedule(
                medication_id=medication.id,
                local_time="20:00",
                timezone=senior.timezone,
                dose_quantity="1 tablet",
                late_after_minutes=30,
                missed_after_minutes=120,
            ),
        ]
    )

    session.add(
        Reminder(
            family_id=family.id,
            senior_profile_id=senior.id,
            type=ReminderType.HYDRATION,
            title="Drink a glass of water",
            local_time="11:00",
            timezone=senior.timezone,
            created_by_user_id=family.created_by_user_id,
        )
    )
    session.add(
        EmergencyContact(
            family_id=family.id,
            senior_profile_id=senior.id,
            name="Dr. Fictional",
            phone="+910000000000",
            relationship_label="Physician",
            priority=1,
            is_primary=True,
            consent_confirmed=True,
        )
    )

    measured = utcnow() - dt.timedelta(hours=2)
    session.add_all(
        [
            HealthReading(
                family_id=family.id,
                senior_profile_id=senior.id,
                metric=HealthMetric.HEART_RATE,
                value=72,
                unit="bpm",
                source=HealthSource.MANUAL_FAMILY,
                measured_at=measured,
            ),
            HealthReading(
                family_id=family.id,
                senior_profile_id=senior.id,
                metric=HealthMetric.OXYGEN_SATURATION,
                value=96,
                unit="%",
                source=HealthSource.MANUAL_FAMILY,
                measured_at=measured,
            ),
        ]
    )
    await session.flush()


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Load Gamira development seed data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate every table before seeding (local only).",
    )
    args = parser.parse_args()
    try:
        await seed(reset=args.reset)
    finally:
        await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
