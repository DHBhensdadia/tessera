"""A CB-CTT instance as Tessera would hold it, and a ledger of what that costs.

Same shape as `importers/itc/apply.py`, and for the same reasons — but a very different
outcome. 4.0 dropped **all 52,254** ITC-2019 classes because a Tessera session must be taught
to a student group and those instances stated individual enrolments with no programme tree.
**A curriculum is a cohort**, so that barrier is simply absent here and the teaching structure
crosses intact.

Two things still do not fit, and both were named in plan 4.2 §1 before any of this was written:

* **Room capacity is soft in CB-CTT and a hard invariant in Tessera.** A published-optimal
  CB-CTT solution may seat eighty students in a room for sixty and pay a penalty. Tessera
  refuses it. Mapped faithfully anyway (D6): an instance with no feasible Tessera timetable
  under the harder rule is a fact about Tessera worth knowing, not a failure of the solver.
* **Unavailability is per course**, and Tessera has it per instructor or per room. A teacher
  who teaches two courses cannot carry one course's unavailability without imposing it on the
  other, so it is carried only where the teacher teaches nothing else, and reported otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

from tessera.domain.entities import Room, Session, SessionKind, Unavailability
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.importers.cbctt.format import Instance

#: CB-CTT periods have no clock time. An hour from nine is a readable default and nothing in
#: the model depends on it — the grid's job here is to fix how many slots a day has.
SLOT_MINUTES = 60
DAY_START = 9 * 60


@dataclass(frozen=True, slots=True)
class Entry:
    what: str
    count: int
    because: str = ""


@dataclass(frozen=True)
class Mapped:
    """Everything a solve needs, plus what the crossing cost."""

    instance: str
    grid: TimeGrid
    rooms: tuple[Room, ...]
    groups: GroupSet
    sessions: tuple[Session, ...]
    unavailability: tuple[Unavailability, ...] = ()
    carried: tuple[Entry, ...] = ()
    dropped: tuple[Entry, ...] = ()

    @property
    def is_lossless(self) -> bool:
        return not self.dropped


def mapped(instance: Instance) -> Mapped:
    """Turn a CB-CTT instance into a term Tessera can hold."""
    grid = TimeGrid(
        days=instance.days,
        slots_per_day=instance.periods_per_day,
        slot_minutes=SLOT_MINUTES,
        day_start_minute=DAY_START,
    )

    groups, group_of_course, group_of_curriculum = _groups(instance)
    rooms = tuple(
        Room(id=RoomId(n), name=room.id, capacity=room.capacity)
        for n, room in enumerate(instance.rooms, start=1)
    )
    teachers = {
        teacher: InstructorId(n)
        for n, teacher in enumerate(sorted({c.teacher for c in instance.courses}), start=1)
    }

    sessions: list[Session] = []
    for course in instance.courses:
        attending = frozenset(
            {group_of_course[course.id]}
            | {
                group_of_curriculum[curriculum.id]
                for curriculum in instance.curricula
                if course.id in curriculum.courses
            }
        )
        for occurrence in range(course.lectures):
            sessions.append(
                Session(
                    id=SessionId(len(sessions) + 1),
                    kind=SessionKind.LECTURE,
                    duration_slots=1,
                    occurrence=occurrence,
                    attendee_ids=attending,
                    instructor_ids=frozenset({teachers[course.teacher]}),
                )
            )

    unavailability, dropped = _unavailability(instance, teachers, grid)

    return Mapped(
        instance=instance.name,
        grid=grid,
        rooms=rooms,
        groups=groups,
        sessions=tuple(sessions),
        unavailability=tuple(unavailability),
        carried=(
            Entry("rooms", len(rooms)),
            Entry("courses", len(instance.courses)),
            Entry("curricula", len(instance.curricula), "each becomes a student group"),
            Entry("teachers", len(teachers)),
            Entry("lectures", len(sessions), "one session each, one period long"),
            Entry("teaching days", instance.days),
        ),
        dropped=tuple(dropped),
    )


def _groups(
    instance: Instance,
) -> tuple[GroupSet, dict[str, StudentGroupId], dict[str, StudentGroupId]]:
    """Two kinds of group, because one cannot do both jobs.

    A **curriculum group** carries the conflicts: two courses in one curriculum share it, so
    Tessera's `group_not_double_booked` refuses them at the same hour, which is exactly
    CB-CTT's `Conflicts`.

    A **course group** carries the headcount, and it has to be separate. Tessera derives how
    many students a session seats from the sizes of its groups; CB-CTT states the count per
    *course*, and a course may belong to several curricula — so putting the number on the
    curricula would count the same students once per curriculum and reject rooms that fit.
    The curriculum groups therefore have no size of their own, and the course group has it all.

    A course in no curriculum still has a course group, which is also what lets it exist at
    all: a Tessera session must be taught to somebody.
    """
    groups: list[StudentGroup] = []
    of_course: dict[str, StudentGroupId] = {}
    of_curriculum: dict[str, StudentGroupId] = {}

    for course in instance.courses:
        group_id = StudentGroupId(len(groups) + 1)
        groups.append(
            StudentGroup(
                id=group_id,
                name=f"{course.id} students",
                size=course.students,
                kind=GroupKind.STRUCTURAL,
            )
        )
        of_course[course.id] = group_id

    for curriculum in instance.curricula:
        group_id = StudentGroupId(len(groups) + 1)
        groups.append(
            StudentGroup(id=group_id, name=curriculum.id, size=0, kind=GroupKind.STRUCTURAL)
        )
        of_curriculum[curriculum.id] = group_id

    return GroupSet(groups), of_course, of_curriculum


def _unavailability(
    instance: Instance, teachers: dict[str, InstructorId], grid: TimeGrid
) -> tuple[list[Unavailability], list[Entry]]:
    """Course-level unavailability, carried where it can be without over-reaching.

    CB-CTT says *"if the teacher of the course is not available to teach that course at a given
    period"*. Tessera blocks an instructor or a room, never a course — so where a teacher
    teaches exactly one course the two are the same statement, and where they teach several it
    is not: blocking the teacher would forbid their other courses at that hour, which the
    instance does not say.

    Widening it would be a **wrong** import rather than a lossy one — the timetable it forbids
    might be the published optimum — so the rest is dropped and counted.
    """
    courses_by_teacher: dict[str, list[str]] = {}
    for course in instance.courses:
        courses_by_teacher.setdefault(course.teacher, []).append(course.id)

    carried: list[Unavailability] = []
    widened = 0
    for row in instance.unavailable:
        teacher = instance.teacher_of(row.course)
        if len(courses_by_teacher[teacher]) > 1:
            widened += 1
            continue
        carried.append(
            Unavailability(
                instructor_id=teachers[teacher],
                slot=row.day * grid.slots_per_day + row.period,
                reason=f"{row.course} unavailable",
            )
        )

    dropped = [
        Entry(
            "soft constraints",
            4,
            "RoomCapacity, MinimumWorkingDays, CurriculumCompactness and RoomStability are "
            "what a CB-CTT solution is *scored* on; 4.2 places lectures and does not weigh "
            "them, and 4.5 scores an instance as written rather than as imported",
        )
    ]
    if widened:
        dropped.append(
            Entry(
                "unavailability",
                widened,
                "names a course whose teacher teaches others; blocking the teacher would "
                "forbid those too, which the instance does not say",
            )
        )
    return carried, dropped
