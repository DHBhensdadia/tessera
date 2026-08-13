"""Time grids, terms, offerings, session templates and sessions."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from tessera.api.schemas.common import Reference, Wire
from tessera.domain.entities import SessionKind, UnavailabilityKind


class TimeGridCreate(Wire):
    institution_id: int
    name: str = "Default"
    days: int = Field(ge=1, le=7)
    slots_per_day: int = Field(ge=1, le=96)
    slot_minutes: int = Field(
        ge=5, le=120, description="30 by default; 15 allows 45-minute periods."
    )
    day_start_minute: int = Field(ge=0, lt=1440)
    break_slots: list[int] = Field(
        default_factory=list,
        description="Slot-of-day indices that are protected, such as lunch. Recurs daily.",
    )


class TimeGridRead(Wire):
    id: int
    name: str
    days: int
    slots_per_day: int
    slot_minutes: int
    day_start_minute: int
    break_slots: list[int] = Field(default_factory=list)
    slot_count: int = Field(default=0, description="Total slots in the week, breaks included.")


class TermCreate(Wire):
    institution_id: int
    time_grid_id: int
    academic_year: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    starts_on: date | None = None
    ends_on: date | None = None


class TermUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    starts_on: date | None = None
    ends_on: date | None = None


class TermRead(Wire):
    id: int
    academic_year: str
    name: str
    starts_on: date | None
    ends_on: date | None
    time_grid: Reference | None = None


class TermDuplicate(Wire):
    """What to carry forward when rolling a term into the next one.

    Everything structural defaults to true and the timetable defaults to false: the
    point of duplicating is that the second semester costs an hour rather than a day.
    """

    name: str = Field(min_length=1, max_length=100)
    academic_year: str = Field(min_length=1, max_length=20)
    copy_rooms: bool = True
    copy_instructors: bool = True
    copy_groups: bool = True
    copy_courses: bool = True
    copy_constraints: bool = True
    copy_offerings: bool = False
    copy_assignments: bool = False


class OfferingCreate(Wire):
    term_id: int
    course_id: int


class OfferingRead(Wire):
    id: int
    term_id: int
    course: Reference | None = None
    session_count: int = Field(default=0, description="Sessions this offering expands to.")


class SessionTemplateCreate(Wire):
    offering_id: int
    kind: SessionKind = SessionKind.LECTURE
    duration_slots: int = Field(ge=1)
    per_week: int = Field(ge=1)
    split_per_attendee: bool = Field(
        default=False,
        description="When true each attending group gets its own parallel sessions — "
        "how one lab becomes three.",
    )
    attendee_ids: list[int] = Field(min_length=1)
    instructor_ids: list[int] = Field(default_factory=list)
    required_feature_ids: list[int] = Field(default_factory=list)


class SessionTemplateUpdate(Wire):
    """What can change about a component after it has been created.

    **Multiplicity only.** ``kind``, ``duration_slots``, ``instructor_ids`` and
    ``required_feature_ids`` are absent deliberately: those are *copied* into each
    session so a session can diverge from its template, and there is no honest way to
    propagate a change to them. Overwriting would revert deliberate per-session edits;
    not overwriting would leave a template and its sessions silently disagreeing. To
    change the shape of a component, delete it and add it again.

    What is here is what reconciliation can act on: how many, and taught to whom.
    """

    per_week: int | None = Field(default=None, ge=1)
    split_per_attendee: bool | None = None
    attendee_ids: list[int] | None = Field(default=None, min_length=1)


class SessionTemplateRead(Wire):
    id: int
    offering_id: int
    kind: SessionKind
    duration_slots: int
    per_week: int
    split_per_attendee: bool
    attendees: list[Reference] = Field(default_factory=list)
    instructors: list[Reference] = Field(default_factory=list)
    required_features: list[Reference] = Field(default_factory=list)
    session_count: int = 0


class SessionUpdate(Wire):
    duration_slots: int | None = Field(default=None, ge=1)
    instructor_ids: list[int] | None = None
    required_feature_ids: list[int] | None = None


class SessionRead(Wire):
    id: int
    offering_id: int
    course: Reference | None = None
    kind: SessionKind
    duration_slots: int
    occurrence: int
    attendees: list[Reference] = Field(default_factory=list)
    instructors: list[Reference] = Field(default_factory=list)
    required_features: list[Reference] = Field(default_factory=list)
    headcount: int = 0


class UnavailabilityCreate(Wire):
    kind: UnavailabilityKind
    subject_id: int = Field(description="Instructor or room id, per kind.")
    slots: list[int] = Field(min_length=1, description="Week-absolute slot indices.")
    reason: str = ""


class UnavailabilityRead(Wire):
    kind: UnavailabilityKind
    subject_id: int
    slot: int
    reason: str
