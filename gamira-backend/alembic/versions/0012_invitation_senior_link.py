"""Add senior_profile_id to family_invitations.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-19

A cared-for person's own sign-in was never actually linkable to their
``SeniorProfile`` outside of seed data: nothing set ``SeniorProfile.user_id``,
and an invitation had no way to say "this one is for the senior, not a new
caregiver". This column lets ``create_invitation`` carry that intent, and
``accept_invitation`` link the profile instead of only creating a viewer
membership.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("family_invitations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("senior_profile_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_family_invitations_senior_profile_id"),
            ["senior_profile_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_family_invitations_senior_profile_id_senior_profiles"),
            "senior_profiles",
            ["senior_profile_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("family_invitations", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_family_invitations_senior_profile_id_senior_profiles"),
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_family_invitations_senior_profile_id"))
        batch_op.drop_column("senior_profile_id")
