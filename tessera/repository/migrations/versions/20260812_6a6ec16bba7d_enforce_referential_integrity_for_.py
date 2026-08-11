"""Enforce referential integrity for assignments and unavailability

Three rules that the schema previously left to convention, each demonstrated to be
breakable before this change:

* a timetable could hold a session belonging to a different term
* unavailability could name an instructor or room that did not exist, and survived the
  deletion of the one it did name
* four foreign keys were unindexed

Autogenerate ordered these alphabetically, which fails: ``assignment`` is rebuilt first
and references unique constraints on ``session`` and ``timetable`` that do not yet
exist. The operations below are ordered by dependency instead — targets before the keys
that point at them.

``term_id`` is added NOT NULL without a default, which is safe only because no released
version has ever written a project file. A migration touching real data would need a
backfill step here.

Revision ID: 6a6ec16bba7d
Revises: f6949c870ee2
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6a6ec16bba7d"
down_revision: str | Sequence[str] | None = "f6949c870ee2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Composite targets first: a composite foreign key needs a unique index on the
    #    columns it points at.
    with op.batch_alter_table("offering", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_offering_id_term", ["id", "term_id"])

    with op.batch_alter_table("timetable", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_timetable_id_term", ["id", "term_id"])

    # 2. session gains term_id and is tied to its offering's term, so the denormalised
    #    copy cannot drift.
    with op.batch_alter_table("session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("term_id", sa.Integer(), nullable=False))
        batch_op.create_index(batch_op.f("ix_session_term_id"), ["term_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_session_template_id"), ["template_id"], unique=False)
        batch_op.create_unique_constraint("uq_session_id_term", ["id", "term_id"])
        batch_op.drop_constraint("fk_session_offering_id_offering", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_session_offering_term",
            "offering",
            ["offering_id", "term_id"],
            ["id", "term_id"],
            ondelete="CASCADE",
        )

    # 3. assignment can now be tied to both, which is what refuses a cross-term placement.
    with op.batch_alter_table("assignment", schema=None) as batch_op:
        batch_op.add_column(sa.Column("term_id", sa.Integer(), nullable=False))
        batch_op.create_index(batch_op.f("ix_assignment_term_id"), ["term_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_session_id"), ["session_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assignment_room_id"), ["room_id"], unique=False)
        batch_op.drop_constraint("fk_assignment_session_id_session", type_="foreignkey")
        batch_op.drop_constraint("fk_assignment_timetable_id_timetable", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_assignment_session_term",
            "session",
            ["session_id", "term_id"],
            ["id", "term_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_assignment_timetable_term",
            "timetable",
            ["timetable_id", "term_id"],
            ["id", "term_id"],
            ondelete="CASCADE",
        )

    # 4. unavailability: an exclusive arc with real foreign keys, replacing a `kind`
    #    discriminator beside an untyped id that could not be constrained at all.
    with op.batch_alter_table("unavailability", schema=None) as batch_op:
        batch_op.add_column(sa.Column("instructor_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("room_id", sa.Integer(), nullable=True))
        batch_op.drop_constraint(batch_op.f("uq_unavailability_term_id"), type_="unique")
        batch_op.create_unique_constraint(
            batch_op.f("uq_unavailability_term_id"),
            ["term_id", "instructor_id", "room_id", "slot"],
        )
        batch_op.create_index(
            batch_op.f("ix_unavailability_instructor_id"), ["instructor_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_unavailability_room_id"), ["room_id"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_unavailability_instructor_id_instructor"),
            "instructor",
            ["instructor_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_unavailability_room_id_room"),
            "room",
            ["room_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_unavailability_exactly_one_subject"),
            "(instructor_id IS NOT NULL) + (room_id IS NOT NULL) = 1",
        )
        batch_op.drop_column("subject_id")
        batch_op.drop_column("kind")

    # 5. Remaining index.
    with op.batch_alter_table("student_group", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_student_group_program_id"), ["program_id"], unique=False
        )


def downgrade() -> None:
    # Reverse order: dependants before the things they depend on.
    with op.batch_alter_table("student_group", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_student_group_program_id"))

    with op.batch_alter_table("unavailability", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kind", sa.VARCHAR(length=20), nullable=False))
        batch_op.add_column(sa.Column("subject_id", sa.INTEGER(), nullable=False))
        batch_op.drop_constraint(
            batch_op.f("ck_unavailability_exactly_one_subject"), type_="check"
        )
        batch_op.drop_constraint(
            batch_op.f("fk_unavailability_room_id_room"), type_="foreignkey"
        )
        batch_op.drop_constraint(
            batch_op.f("fk_unavailability_instructor_id_instructor"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_unavailability_room_id"))
        batch_op.drop_index(batch_op.f("ix_unavailability_instructor_id"))
        batch_op.drop_constraint(batch_op.f("uq_unavailability_term_id"), type_="unique")
        batch_op.create_unique_constraint(
            batch_op.f("uq_unavailability_term_id"), ["term_id", "kind", "subject_id", "slot"]
        )
        batch_op.drop_column("room_id")
        batch_op.drop_column("instructor_id")

    with op.batch_alter_table("assignment", schema=None) as batch_op:
        batch_op.drop_constraint("fk_assignment_timetable_term", type_="foreignkey")
        batch_op.drop_constraint("fk_assignment_session_term", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_assignment_session_id_session",
            "session",
            ["session_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_assignment_timetable_id_timetable",
            "timetable",
            ["timetable_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_index(batch_op.f("ix_assignment_room_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_session_id"))
        batch_op.drop_index(batch_op.f("ix_assignment_term_id"))
        batch_op.drop_column("term_id")

    with op.batch_alter_table("session", schema=None) as batch_op:
        batch_op.drop_constraint("fk_session_offering_term", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_session_offering_id_offering",
            "offering",
            ["offering_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_constraint("uq_session_id_term", type_="unique")
        batch_op.drop_index(batch_op.f("ix_session_template_id"))
        batch_op.drop_index(batch_op.f("ix_session_term_id"))
        batch_op.drop_column("term_id")

    with op.batch_alter_table("timetable", schema=None) as batch_op:
        batch_op.drop_constraint("uq_timetable_id_term", type_="unique")

    with op.batch_alter_table("offering", schema=None) as batch_op:
        batch_op.drop_constraint("uq_offering_id_term", type_="unique")
