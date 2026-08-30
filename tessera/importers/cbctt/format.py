"""The `.ctt` file, as the specification says it.

Same discipline as `importers/itc` and for the same reason (4.0's D6): read the file into
something that mirrors it, then map separately. A reader that parsed straight into Tessera's
model would make the fidelity report a measurement of itself.

The format is from the competition's own technical report — Di Gaspero, McCollum and Schaerf,
*QUB/IEEE/Tech/ITC2007/CurriculumCTT/v1.0/1*, §4.1 — not from memory or from a summary. That
distinction earned itself here: a summary of the same report gave the wrong penalty for
`RoomCapacity` and mangled all four hard constraints.

```
Courses:                  <CourseID> <Teacher> <#Lectures> <MinWorkingDays> <#Students>
Rooms:                    <RoomID> <Capacity>
Curricula:                <CurriculumID> <#Courses> <MemberID> ... <MemberID>
Unavailability_Constraints: <CourseID> <Day> <Day_Period>
```

IDs are strings without blanks; days and periods count from zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: The header keys, in the order the specification fixes them.
HEADER = ("Name", "Courses", "Rooms", "Days", "Periods_per_day", "Curricula", "Constraints")


class MalformedInstanceError(Exception):
    """The file is not a `.ctt` instance this reader will guess at.

    Guessing is the failure that matters: an instance is somebody else's data, read once and
    then reported on in numbers people are asked to trust.
    """


@dataclass(frozen=True, slots=True)
class Course:
    id: str
    teacher: str
    lectures: int
    """How many times a week it is taught. Each becomes one session."""

    min_working_days: int
    """The days its lectures should be spread over. Soft in this format — `MinimumWorkingDays`
    costs 5 points per day below it — so it constrains nothing here in 4.2."""

    students: int


@dataclass(frozen=True, slots=True)
class Room:
    id: str
    capacity: int


@dataclass(frozen=True, slots=True)
class Curriculum:
    """A set of courses taken by the same students.

    **The thing ITC-2019 did not have.** 4.0 dropped all 52,254 of its classes because a
    Tessera session must be taught to a student group and those instances stated individual
    enrolments with no programme tree. A curriculum *is* a cohort, so that barrier is absent
    here.
    """

    id: str
    courses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Unavailable:
    """An hour a course cannot be taught in, because its teacher is not there then."""

    course: str
    day: int
    period: int


@dataclass(frozen=True)
class Instance:
    name: str
    days: int
    periods_per_day: int
    courses: tuple[Course, ...]
    rooms: tuple[Room, ...]
    curricula: tuple[Curriculum, ...]
    unavailable: tuple[Unavailable, ...]

    @property
    def periods(self) -> int:
        return self.days * self.periods_per_day

    @property
    def lectures(self) -> int:
        """Every lecture that must be placed — the number of sessions a mapping produces."""
        return sum(course.lectures for course in self.courses)

    def teacher_of(self, course_id: str) -> str:
        return next(c.teacher for c in self.courses if c.id == course_id)


def read(source: Path | str, name: str = "") -> Instance:
    """Parse one `.ctt` instance."""
    text = source if isinstance(source, str) else source.read_text()
    lines = [line.rstrip() for line in text.splitlines()]

    header: dict[str, str] = {}
    for key in HEADER:
        header[key] = _header(lines, key, name or str(source))

    sections = _sections(lines, name or str(source))
    return Instance(
        name=header["Name"],
        days=_int(header["Days"], "Days"),
        periods_per_day=_int(header["Periods_per_day"], "Periods_per_day"),
        courses=tuple(_course(row) for row in sections["COURSES"]),
        rooms=tuple(_room(row) for row in sections["ROOMS"]),
        curricula=tuple(_curriculum(row) for row in sections["CURRICULA"]),
        unavailable=tuple(_unavailable(row) for row in sections["UNAVAILABILITY_CONSTRAINTS"]),
    )


def _header(lines: list[str], key: str, where: str) -> str:
    for line in lines:
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    raise MalformedInstanceError(f"{where} has no {key!r} in its header")


def _sections(lines: list[str], where: str) -> dict[str, list[list[str]]]:
    """The four blocks, split on their headings.

    `END.` closes the file. Blank lines separate blocks and carry no meaning, which is why
    they are dropped rather than counted — a reader that treated one as a row would produce a
    course with no fields and a confusing message about it.
    """
    wanted = ("COURSES:", "ROOMS:", "CURRICULA:", "UNAVAILABILITY_CONSTRAINTS:")
    found: dict[str, list[list[str]]] = {}
    current: str | None = None

    for line in lines:
        stripped = line.strip()
        if stripped in wanted:
            current = stripped.rstrip(":")
            found[current] = []
        elif stripped == "END.":
            current = None
        elif stripped and current is not None:
            found[current].append(stripped.split())

    missing = [section.rstrip(":") for section in wanted if section.rstrip(":") not in found]
    if missing:
        raise MalformedInstanceError(f"{where} is missing the section(s) {missing}")
    return found


def _course(row: list[str]) -> Course:
    if len(row) != 5:
        raise MalformedInstanceError(
            f"a course needs five fields — id, teacher, lectures, min days, students — got {row}"
        )
    return Course(
        id=row[0],
        teacher=row[1],
        lectures=_int(row[2], "lectures"),
        min_working_days=_int(row[3], "min working days"),
        students=_int(row[4], "students"),
    )


def _room(row: list[str]) -> Room:
    if len(row) != 2:
        raise MalformedInstanceError(f"a room needs an id and a capacity, got {row}")
    return Room(id=row[0], capacity=_int(row[1], "capacity"))


def _curriculum(row: list[str]) -> Curriculum:
    if len(row) < 2:
        raise MalformedInstanceError(f"a curriculum needs an id and a count, got {row}")
    declared = _int(row[1], "course count")
    members = tuple(row[2:])
    if len(members) != declared:
        raise MalformedInstanceError(
            f"curriculum {row[0]!r} declares {declared} courses and lists {len(members)}"
        )
    return Curriculum(id=row[0], courses=members)


def _unavailable(row: list[str]) -> Unavailable:
    if len(row) != 3:
        raise MalformedInstanceError(f"an unavailability needs a course, day and period, got {row}")
    return Unavailable(course=row[0], day=_int(row[1], "day"), period=_int(row[2], "period"))


def _int(value: str, what: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise MalformedInstanceError(f"{what} {value!r} is not a number") from error
