"""SQLAlchemy mapping.

Deliberately a separate set of classes from ``tessera.domain``. The duplication is the
price of Decision #14: the domain stays free of SQLAlchemy so it can be used by the
solver, the exporters and the CLI without dragging a database along, and the storage
layout stays free to differ from the wire and in-memory shapes.

Every table is scoped by term where scheduling data is concerned, so that duplicating a
term forward copies rows rather than sharing them.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Explicit naming, because SQLite cannot ALTER an unnamed constraint. Without this,
# Alembic generates anonymous constraints that later migrations are unable to drop —
# a problem that only appears months in, when the first schema change lands.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Common base: shared metadata, and the surrogate key every table carries.

    Declaring ``id`` here rather than on each model removes twenty repetitions and,
    more usefully, gives generic helpers a bound to work against — ``_resolve`` in
    mappers.py can be written once over ``type[Base]`` instead of per model.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


# ---------------------------------------------------------------------------
# Association tables. No payload of their own, so they are Core tables rather
# than mapped classes.
# ---------------------------------------------------------------------------

room_feature = Table(
    "room_feature",
    Base.metadata,
    Column("room_id", ForeignKey("room.id", ondelete="CASCADE"), primary_key=True),
    Column("feature_id", ForeignKey("feature.id", ondelete="CASCADE"), primary_key=True),
)

group_member = Table(
    "group_member",
    Base.metadata,
    Column("cohort_id", ForeignKey("student_group.id", ondelete="CASCADE"), primary_key=True),
    Column("member_id", ForeignKey("student_group.id", ondelete="CASCADE"), primary_key=True),
)

template_attendee = Table(
    "template_attendee",
    Base.metadata,
    Column("template_id", ForeignKey("session_template.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("student_group.id", ondelete="CASCADE"), primary_key=True),
)

template_instructor = Table(
    "template_instructor",
    Base.metadata,
    Column("template_id", ForeignKey("session_template.id", ondelete="CASCADE"), primary_key=True),
    Column("instructor_id", ForeignKey("instructor.id", ondelete="CASCADE"), primary_key=True),
)

template_feature = Table(
    "template_feature",
    Base.metadata,
    Column("template_id", ForeignKey("session_template.id", ondelete="CASCADE"), primary_key=True),
    Column("feature_id", ForeignKey("feature.id", ondelete="CASCADE"), primary_key=True),
)

session_attendee = Table(
    "session_attendee",
    Base.metadata,
    Column("session_id", ForeignKey("session.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("student_group.id", ondelete="CASCADE"), primary_key=True),
)

session_instructor = Table(
    "session_instructor",
    Base.metadata,
    Column("session_id", ForeignKey("session.id", ondelete="CASCADE"), primary_key=True),
    Column("instructor_id", ForeignKey("instructor.id", ondelete="CASCADE"), primary_key=True),
)

session_feature = Table(
    "session_feature",
    Base.metadata,
    Column("session_id", ForeignKey("session.id", ondelete="CASCADE"), primary_key=True),
    Column("feature_id", ForeignKey("feature.id", ondelete="CASCADE"), primary_key=True),
)

constraint_target = Table(
    "constraint_target",
    Base.metadata,
    Column("constraint_id", ForeignKey("constraint.id", ondelete="CASCADE"), primary_key=True),
    Column("session_id", ForeignKey("session.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


class Institution(Base):
    __tablename__ = "institution"
    name: Mapped[str] = mapped_column(String(200))


class Department(Base):
    __tablename__ = "department"
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(32), default="")


class Building(Base):
    __tablename__ = "building"
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))


class Feature(Base):
    __tablename__ = "feature"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))


class Room(Base):
    __tablename__ = "room"
    building_id: Mapped[int | None] = mapped_column(
        ForeignKey("building.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    features: Mapped[list[Feature]] = relationship(secondary=room_feature, lazy="selectin")


class Instructor(Base):
    __tablename__ = "instructor"
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    max_slots_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_slots_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_consecutive_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Program(Base):
    __tablename__ = "program"
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(32), default="")


class StudentGroup(Base):
    __tablename__ = "student_group"
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("program.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="structural")
    size: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("student_group.id", ondelete="CASCADE"), nullable=True, index=True
    )
    members: Mapped[list[StudentGroup]] = relationship(
        secondary=group_member,
        primaryjoin=lambda: StudentGroup.id == group_member.c.cohort_id,
        secondaryjoin=lambda: StudentGroup.id == group_member.c.member_id,
        lazy="selectin",
    )


class Course(Base):
    __tablename__ = "course"
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    credits: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


class TimeGrid(Base):
    __tablename__ = "time_grid"
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), default="Default")
    days: Mapped[int] = mapped_column(Integer)
    slots_per_day: Mapped[int] = mapped_column(Integer)
    slot_minutes: Mapped[int] = mapped_column(Integer)
    day_start_minute: Mapped[int] = mapped_column(Integer)
    breaks: Mapped[list[TimeGridBreak]] = relationship(
        back_populates="grid", cascade="all, delete-orphan", lazy="selectin"
    )


class TimeGridBreak(Base):
    """A non-teaching slot-of-day, such as lunch.

    A row rather than a packed field so the interface can name it, and so a query can
    ask which grids protect a given hour.
    """

    __tablename__ = "time_grid_break"
    __table_args__ = (UniqueConstraint("grid_id", "slot_of_day"),)
    grid_id: Mapped[int] = mapped_column(ForeignKey("time_grid.id", ondelete="CASCADE"))
    slot_of_day: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(100), default="")
    grid: Mapped[TimeGrid] = relationship(back_populates="breaks")


class Term(Base):
    __tablename__ = "term"
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id", ondelete="CASCADE"))
    time_grid_id: Mapped[int] = mapped_column(ForeignKey("time_grid.id", ondelete="RESTRICT"))
    academic_year: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)


# ---------------------------------------------------------------------------
# Teaching
# ---------------------------------------------------------------------------


class Offering(Base):
    __tablename__ = "offering"
    __table_args__ = (
        UniqueConstraint("term_id", "course_id"),
        # Redundant on its own — id is already unique — but required as the target of
        # session's composite key, which is what stops a session drifting to another
        # term's offering.
        UniqueConstraint("id", "term_id", name="uq_offering_id_term"),
    )
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id", ondelete="CASCADE"))


class SessionTemplate(Base):
    __tablename__ = "session_template"
    offering_id: Mapped[int] = mapped_column(
        ForeignKey("offering.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="lecture")
    duration_slots: Mapped[int] = mapped_column(Integer)
    per_week: Mapped[int] = mapped_column(Integer)
    split_per_attendee: Mapped[bool] = mapped_column(Boolean, default=False)
    attendees: Mapped[list[StudentGroup]] = relationship(
        secondary=template_attendee, lazy="selectin"
    )
    instructors: Mapped[list[Instructor]] = relationship(
        secondary=template_instructor, lazy="selectin"
    )
    required_features: Mapped[list[Feature]] = relationship(
        secondary=template_feature, lazy="selectin"
    )


class Session(Base):
    """The atom the solver places.

    ``term_id`` is denormalised from the offering on purpose. Without it the database
    cannot express "an assignment's session and timetable belong to the same term", and
    that rule would rest on every caller remembering it. The composite key below keeps
    the copy honest.
    """

    __tablename__ = "session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["offering_id", "term_id"],
            ["offering.id", "offering.term_id"],
            ondelete="CASCADE",
            name="fk_session_offering_term",
        ),
        UniqueConstraint("id", "term_id", name="uq_session_id_term"),
    )

    offering_id: Mapped[int] = mapped_column(Integer, index=True)
    term_id: Mapped[int] = mapped_column(Integer, index=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("session_template.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="lecture")
    duration_slots: Mapped[int] = mapped_column(Integer)
    occurrence: Mapped[int] = mapped_column(Integer, default=0)
    attendees: Mapped[list[StudentGroup]] = relationship(
        secondary=session_attendee, lazy="selectin"
    )
    instructors: Mapped[list[Instructor]] = relationship(
        secondary=session_instructor, lazy="selectin"
    )
    required_features: Mapped[list[Feature]] = relationship(
        secondary=session_feature, lazy="selectin"
    )


class Unavailability(Base):
    """A slot in which one instructor or one room may not be used.

    Two nullable foreign keys with a check that exactly one is set — the exclusive-arc
    pattern. The obvious alternative, a `kind` discriminator beside an untyped
    `subject_id`, cannot be given a foreign key at all: deleting an instructor would
    leave their unavailability behind, and a later instructor reusing that id would
    silently inherit it.
    """

    __tablename__ = "unavailability"
    __table_args__ = (
        UniqueConstraint("term_id", "instructor_id", "room_id", "slot"),
        CheckConstraint(
            "(instructor_id IS NOT NULL) + (room_id IS NOT NULL) = 1",
            name="exactly_one_subject",
        ),
    )
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id", ondelete="CASCADE"), index=True)
    instructor_id: Mapped[int | None] = mapped_column(
        ForeignKey("instructor.id", ondelete="CASCADE"), nullable=True, index=True
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="CASCADE"), nullable=True, index=True
    )
    slot: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default="")


class Constraint(Base):
    __tablename__ = "constraint"
    term_id: Mapped[int] = mapped_column(ForeignKey("term.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    is_hard: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    params: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    targets: Mapped[list[Session]] = relationship(secondary=constraint_target, lazy="selectin")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class Timetable(Base):
    __tablename__ = "timetable"
    __table_args__ = (UniqueConstraint("id", "term_id", name="uq_timetable_id_term"),)

    term_id: Mapped[int] = mapped_column(ForeignKey("term.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="Draft")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("timetable.id", ondelete="SET NULL"), nullable=True
    )
    penalty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    penalty_breakdown: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Assignment(Base):
    """One session placed at a time and in a room.

    ``term_id`` exists so the composite keys below can refuse a timetable holding a
    session from a different term. Without them the database accepts the mismatch
    silently, and term duplication is exactly where it would occur.
    """

    __tablename__ = "assignment"
    __table_args__ = (
        UniqueConstraint("timetable_id", "session_id"),
        ForeignKeyConstraint(
            ["timetable_id", "term_id"],
            ["timetable.id", "timetable.term_id"],
            ondelete="CASCADE",
            name="fk_assignment_timetable_term",
        ),
        ForeignKeyConstraint(
            ["session_id", "term_id"],
            ["session.id", "session.term_id"],
            ondelete="CASCADE",
            name="fk_assignment_session_term",
        ),
    )
    timetable_id: Mapped[int] = mapped_column(Integer, index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    term_id: Mapped[int] = mapped_column(Integer, index=True)
    start_slot: Mapped[int] = mapped_column(Integer)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id", ondelete="RESTRICT"), index=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Command(Base):
    __tablename__ = "command"
    __table_args__ = (UniqueConstraint("timetable_id", "sequence"),)
    timetable_id: Mapped[int] = mapped_column(
        ForeignKey("timetable.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(300), default="")
    before: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    after: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
