"""The `.sol` file — where a lecture ended up, in the format the competition scores.

One line per lecture, `<CourseID> <RoomID> <Day> <Day_Period>`, from the same technical
report the instance format came from (Di Gaspero, McCollum and Schaerf, §4.2). Days and
periods count from zero, exactly as they do in the `.ctt`.

**Why this exists at all**, given that nothing in Tessera reads it: a benchmark result nobody
can check is a claim. Writing the solution in the competition's own format means the number
this project publishes can be handed to a validator written by somebody else, and that is the
only kind of agreement that is not two readings by the same author.

The reader is deliberately strict about arity and about integers, and deliberately silent
about whether the placements make sense — a file naming a room that does not exist is a
readable file describing a bad solution, and saying which of those it is belongs to
:mod:`tessera.importers.cbctt.score`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tessera.importers.cbctt.format import MalformedInstanceError


@dataclass(frozen=True, slots=True, order=True)
class Placement:
    """One lecture, in a room, at a period.

    Ordered, so a solution has a canonical written form and two runs that found the same
    timetable produce the same file rather than the same set in a different order.
    """

    course: str
    day: int
    period: int
    room: str


def read(source: Path | str) -> tuple[Placement, ...]:
    """Parse a `.sol` file, in the order its lines appear.

    Order is preserved rather than sorted because a duplicate line is a real fault this
    reader must not tidy away — two lectures of one course in one period is exactly what
    `Lectures` forbids, and sorting into a set would delete the evidence.

    Raises `MalformedInstanceError` if a line is not four fields with two integers.
    """
    text = source if isinstance(source, str) else source.read_text()
    placements = []
    for number, line in enumerate(text.splitlines(), start=1):
        row = line.split()
        if not row:
            continue
        if len(row) != 4:
            raise MalformedInstanceError(
                f"line {number} needs four fields — course, room, day, period — got {row}"
            )
        placements.append(
            Placement(
                course=row[0],
                day=_int(row[2], "day", number),
                period=_int(row[3], "period", number),
                room=row[1],
            )
        )
    return tuple(placements)


def write(placements: tuple[Placement, ...]) -> str:
    """The competition's format, sorted, with a trailing newline.

    Sorted so the file is a function of the timetable and not of the order the solver
    happened to report it in. Nothing in the format gives order any meaning, and a file that
    changes when the answer has not would make every diff of a stored result unreadable.
    """
    return "".join(f"{p.course} {p.room} {p.day} {p.period}\n" for p in sorted(placements))


def _int(value: str, what: str, line: int) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise MalformedInstanceError(f"line {line}: {what} {value!r} is not a number") from error
