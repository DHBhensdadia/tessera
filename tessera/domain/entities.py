"""The things a timetable is built from.

Two shapes here are load-bearing and were chosen deliberately:

**Rooms advertise capabilities, not a type.** ``features: frozenset[FeatureId]`` matched
by subset, rather than ``room_type: enum``. An enum works until the first room that is a
chemistry lab *and* has a smartboard, and then every new category is a migration. Sets
scale without one. See R1 §2.

**A course is split three ways.** ``Course`` is the catalogue entry and outlives any
term. ``Offering`` is that course being taught in one term. ``Session`` is a single
teachable block — the atom the solver actually places. Collapsing these means a course
cannot be reused across years, or that "3 lectures and a lab, the lab split three ways"
has nowhere to live.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tessera.domain.ids import (
    BuildingId,
    CourseId,
    DepartmentId,
    FeatureId,
    InstitutionId,
    InstructorId,
    OfferingId,
    ProgramId,
    RoomId,
    SessionId,
    SessionTemplateId,
    StudentGroupId,
    TermId,
    TimeGridId,
)
from tessera.domain.time_grid import Slot


class _Entity(BaseModel):
    model_config = ConfigDict(frozen=True)


class Institution(_Entity):
    id: InstitutionId | None = None
    name: str = Field(min_length=1)


class Department(_Entity):
    id: DepartmentId | None = None
    institution_id: InstitutionId | None = None
    name: str = Field(min_length=1)
    code: str = ""


class Building(_Entity):
    """Grouping used to penalise moving students between sites between sessions."""

    id: BuildingId | None = None
    institution_id: InstitutionId | None = None
    name: str = Field(min_length=1)


class Feature(_Entity):
    """A capability a room can provide and a session can require."""

    id: FeatureId | None = None
    institution_id: InstitutionId | None = None
    name: str = Field(min_length=1)


class Room(_Entity):
    id: RoomId | None = None
    building_id: BuildingId | None = None
    name: str = Field(min_length=1)
    capacity: int = Field(ge=0)
    features: frozenset[FeatureId] = frozenset()

    def can_host(self, headcount: int, required: frozenset[FeatureId]) -> bool:
        return self.capacity >= headcount and required <= self.features


class Instructor(_Entity):
    id: InstructorId | None = None
    department_id: DepartmentId | None = None
    name: str = Field(min_length=1)
    email: str = ""

    max_slots_per_day: int | None = Field(default=None, ge=1)
    max_slots_per_week: int | None = Field(default=None, ge=1)
    max_consecutive_slots: int | None = Field(default=None, ge=1)
    """Load limits. ``None`` means unlimited; they are soft unless a constraint says
    otherwise, since an over-committed instructor should produce a warning rather than
    an unsolvable term."""


class Program(_Entity):
    """A course of study — the root of a student group tree."""

    id: ProgramId | None = None
    department_id: DepartmentId | None = None
    name: str = Field(min_length=1)
    code: str = ""


class Course(_Entity):
    """A catalogue entry, independent of any term."""

    id: CourseId | None = None
    department_id: DepartmentId | None = None
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    credits: int = Field(default=0, ge=0)


class Term(_Entity):
    """One schedulable period, and the unit everything else is scoped by.

    Carries its own ``time_grid_id`` rather than inheriting one globally: duplicating a
    term copies the grid so that later editing the new term's structure cannot silently
    reinterpret the slot indices stored against the old one.
    """

    id: TermId | None = None
    institution_id: InstitutionId | None = None
    time_grid_id: TimeGridId | None = None
    academic_year: str = Field(min_length=1)
    name: str = Field(min_length=1)

    # Calendar dates, unlike everything else about a term, are decoration: scheduling is
    # done entirely in slot indices and nothing here reads these. They exist so a printed
    # timetable can say which weeks it covers, and are optional because a department
    # starts building next year's timetable long before the dates are confirmed.
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def _dates_run_forwards(self) -> Term:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError(f"term {self.name!r} ends before it starts")
        return self


class Offering(_Entity):
    """A course being taught in a particular term."""

    id: OfferingId | None = None
    term_id: TermId | None = None
    course_id: CourseId | None = None


class SessionKind(StrEnum):
    LECTURE = "lecture"
    LAB = "lab"
    TUTORIAL = "tutorial"
    SEMINAR = "seminar"
    OTHER = "other"


class SessionTemplate(_Entity):
    """The weekly pattern for one component of an offering.

    "Three one-hour lectures to the whole intake, plus one two-hour lab per sub-batch"
    is two templates. Templates are an authoring convenience; expanding them produces
    the :class:`Session` rows the solver places.
    """

    id: SessionTemplateId | None = None
    offering_id: OfferingId | None = None
    kind: SessionKind = SessionKind.LECTURE
    duration_slots: int = Field(ge=1)
    per_week: int = Field(ge=1)

    attendee_ids: frozenset[StudentGroupId] = frozenset()
    """Groups this component is taught to. If ``split_per_attendee`` is set, each gets
    its own parallel sessions; otherwise they are taught together."""

    split_per_attendee: bool = False
    instructor_ids: frozenset[InstructorId] = frozenset()
    required_features: frozenset[FeatureId] = frozenset()

    @model_validator(mode="after")
    def _has_attendees(self) -> SessionTemplate:
        if not self.attendee_ids:
            raise ValueError("a session template must be taught to at least one group")
        return self

    @property
    def session_count(self) -> int:
        """How many sessions expanding this template will produce."""
        if self.split_per_attendee:
            return self.per_week * len(self.attendee_ids)
        return self.per_week


class Session(_Entity):
    """One teachable block. **The atom the solver places.**

    Duration, kind and requirements are copied here rather than read through the
    template: a session is the scheduled reality, and editing a template afterwards
    must not silently alter timetables already built from it.
    """

    id: SessionId | None = None
    offering_id: OfferingId | None = None
    template_id: SessionTemplateId | None = None

    kind: SessionKind = SessionKind.LECTURE
    duration_slots: int = Field(ge=1)
    occurrence: int = Field(default=0, ge=0)
    """Which of the weekly repeats this is, counting from zero. Distinguishes the three
    lectures of a course that are otherwise identical."""

    attendee_ids: frozenset[StudentGroupId] = frozenset()
    instructor_ids: frozenset[InstructorId] = frozenset()
    required_features: frozenset[FeatureId] = frozenset()

    @model_validator(mode="after")
    def _has_attendees(self) -> Session:
        if not self.attendee_ids:
            raise ValueError("a session must have at least one attending group")
        return self


class UnavailabilityKind(StrEnum):
    INSTRUCTOR = "instructor"
    ROOM = "room"


class Unavailability(_Entity):
    """A slot in which a specific instructor or room may not be used.

    One row per slot rather than a packed bitmask: the volume is small — a busy week is
    a few dozen rows — and rows can be queried, explained in the interface, and given a
    reason, none of which a blob allows.

    The subject is two optional references rather than a kind plus an untyped id, so the
    database can enforce it. ``kind`` and ``subject_id`` remain available as derived
    properties, since that is the shape the interface and the wire format use.
    """

    term_id: TermId | None = None
    instructor_id: InstructorId | None = None
    room_id: RoomId | None = None
    slot: Slot
    reason: str = ""

    @model_validator(mode="after")
    def _exactly_one_subject(self) -> Unavailability:
        named = [x for x in (self.instructor_id, self.room_id) if x is not None]
        if len(named) != 1:
            raise ValueError(
                "unavailability applies to exactly one instructor or one room, "
                f"but {len(named)} were named"
            )
        return self

    @property
    def kind(self) -> UnavailabilityKind:
        return (
            UnavailabilityKind.INSTRUCTOR
            if self.instructor_id is not None
            else UnavailabilityKind.ROOM
        )

    @property
    def subject_id(self) -> int:
        subject = self.instructor_id if self.instructor_id is not None else self.room_id
        assert subject is not None  # guaranteed by the validator above
        return subject
