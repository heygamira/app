"""Fix two partial unique indexes that never actually fired.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-19

``Enum(..., native_enum=False)`` with no ``values_callable`` stores a Python
enum's *name* ("QUEUED", "REVOKED"), not its ``.value`` ("queued", "revoked").
The ORM round-trips this transparently in both directions, so nothing that
goes through it ever noticed — but ``uq_background_jobs_dedupe_live`` and
``uq_family_memberships_family_user_live`` were both written as raw SQL
predicates against the lowercase value, and so never matched a single row on
either SQLite or PostgreSQL. Running against a real PostgreSQL server for the
first time is what caught it: a test that inserts two live jobs with the same
``dedupe_key`` directly expected an ``IntegrityError`` and the database let
both rows through.

The practical effect: nothing before this migration actually stopped two
concurrent requests from creating two live jobs with the same dedupe key, or
two live memberships for the same user in the same family — the application-
level checks in ``identity_service``/``JobQueue`` were the only thing doing
that, with no database backstop underneath them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_LIVE = "status IN ('queued', 'running')"
_NEW_JOB_LIVE = "status IN ('QUEUED', 'RUNNING')"
_OLD_MEMBERSHIP_LIVE = "status <> 'revoked'"
_NEW_MEMBERSHIP_LIVE = "status <> 'REVOKED'"


def upgrade() -> None:
    with op.batch_alter_table("background_jobs", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_background_jobs_dedupe_live",
            sqlite_where=sa.text(_OLD_JOB_LIVE),
            postgresql_where=sa.text(_OLD_JOB_LIVE),
        )
        batch_op.create_index(
            "uq_background_jobs_dedupe_live",
            ["dedupe_key"],
            unique=True,
            sqlite_where=sa.text(_NEW_JOB_LIVE),
            postgresql_where=sa.text(_NEW_JOB_LIVE),
        )

    with op.batch_alter_table("family_memberships", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_family_memberships_family_user_live",
            sqlite_where=sa.text(_OLD_MEMBERSHIP_LIVE),
            postgresql_where=sa.text(_OLD_MEMBERSHIP_LIVE),
        )
        batch_op.create_index(
            "uq_family_memberships_family_user_live",
            ["family_id", "user_id"],
            unique=True,
            sqlite_where=sa.text(_NEW_MEMBERSHIP_LIVE),
            postgresql_where=sa.text(_NEW_MEMBERSHIP_LIVE),
        )


def downgrade() -> None:
    with op.batch_alter_table("family_memberships", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_family_memberships_family_user_live",
            sqlite_where=sa.text(_NEW_MEMBERSHIP_LIVE),
            postgresql_where=sa.text(_NEW_MEMBERSHIP_LIVE),
        )
        batch_op.create_index(
            "uq_family_memberships_family_user_live",
            ["family_id", "user_id"],
            unique=True,
            sqlite_where=sa.text(_OLD_MEMBERSHIP_LIVE),
            postgresql_where=sa.text(_OLD_MEMBERSHIP_LIVE),
        )

    with op.batch_alter_table("background_jobs", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_background_jobs_dedupe_live",
            sqlite_where=sa.text(_NEW_JOB_LIVE),
            postgresql_where=sa.text(_NEW_JOB_LIVE),
        )
        batch_op.create_index(
            "uq_background_jobs_dedupe_live",
            ["dedupe_key"],
            unique=True,
            sqlite_where=sa.text(_OLD_JOB_LIVE),
            postgresql_where=sa.text(_OLD_JOB_LIVE),
        )
