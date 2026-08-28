"""The ITC-2019 XML, as the XML says it.

**Nothing here knows what Tessera is.** This module reads a competition instance into an
intermediate representation that mirrors the file, and stops. Mapping into Tessera's domain
is `apply.py`, and what that mapping loses is `fidelity.py`.

The separation is Decision D6, and it is the reason the fidelity report can mean anything: a
report comparing a mapped instance against itself measures the parser, not the model. It also
serves Phase 4.5, whose benchmark harness must read an instance **as written** — a score
computed against a lossily imported instance cannot be compared with published results, which
is worse than not benchmarking at all.

So the rule for this file: if the XML says it, it is here, in the XML's own terms. Bitmasks
stay strings because that is what they are; slot indices stay integers counted from midnight
in five-minute steps because that is what they are. Nothing is normalised into Tessera's
vocabulary, and nothing is dropped for being unrepresentable.

**Everything unexpected raises.** A silently defaulted field would put a wrong number in the
fidelity report and nothing would say so — and part 1 of this phase exists precisely because
a parser that mis-reads a week mask makes every later number wrong and quiet about it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


class MalformedInstanceError(Exception):
    """The file is not an instance this parser will guess at.

    Guessing is the failure mode that matters here. An instance is somebody else's data,
    read once and then reported on in numbers people are asked to trust — so a missing
    attribute stops the read rather than becoming a zero.
    """


#: `MaxBlock(60,30)`, `MinGap(4)`, `SameAttendees`. Parameters are positional integers.
_TYPE = re.compile(r"^(?P<name>[A-Za-z]+)(?:\((?P<args>[\d,\s]*)\))?$")


@dataclass(frozen=True, slots=True)
class TimeOption:
    """One time a class may be taught at, and what it costs to choose it.

    ITC gives each class an explicit list of alternatives with penalties. Tessera derives a
    session's domain from rules instead, which is the difference `fidelity.py` has to report
    rather than paper over.
    """

    days: str
    """A bitmask over the week, one character per day, `nrDays` long. `1010100` is
    Monday/Wednesday/Friday."""

    start: int
    """Slots from midnight. With 288 slots a day these are five minutes each, so 102 is
    08:30."""

    length: int
    """In slots. 10 is fifty minutes."""

    weeks: str
    """A bitmask over the term, one character per week, `nrWeeks` long. `0101010101010` is
    every second week — the dimension Tessera does not have."""

    penalty: int

    @property
    def is_every_week(self) -> bool:
        """Whether this option ignores the week dimension entirely.

        The one property of a time option that decides whether Tessera can hold it, so it is
        named here rather than recomputed by every caller.
        """
        return set(self.weeks) == {"1"}


@dataclass(frozen=True, slots=True)
class RoomOption:
    room: int
    penalty: int


@dataclass(frozen=True, slots=True)
class Class:
    id: int
    limit: int
    parent: int | None
    """The class a student must also attend. Present on 13,586 of the 52,254 class
    definitions in the competition set."""

    needs_room: bool
    """`room="false"` in the file. 4,724 classes need no room at all."""

    rooms: tuple[RoomOption, ...]
    times: tuple[TimeOption, ...]


@dataclass(frozen=True, slots=True)
class Subpart:
    id: int
    classes: tuple[Class, ...]


@dataclass(frozen=True, slots=True)
class Config:
    """One way of taking a course — a lecture stream with its own subparts.

    Tessera has no equivalent: a course is offered, and an offering has templates. Alternative
    configurations are a thing the fidelity report has to name.
    """

    id: int
    subparts: tuple[Subpart, ...]


@dataclass(frozen=True, slots=True)
class Course:
    id: int
    configs: tuple[Config, ...]


@dataclass(frozen=True, slots=True)
class Travel:
    room: int
    value: int
    """Slots needed to get between the two rooms. Tessera has buildings and a soft preference
    against moving between them — qualitative where this is quantitative."""


@dataclass(frozen=True, slots=True)
class Unavailable:
    days: str
    start: int
    length: int
    weeks: str


@dataclass(frozen=True, slots=True)
class Room:
    id: int
    capacity: int
    travel: tuple[Travel, ...] = ()
    unavailable: tuple[Unavailable, ...] = ()


@dataclass(frozen=True, slots=True)
class Distribution:
    """One distribution constraint, over a named set of classes.

    Either `required` — a hard rule — or carrying a `penalty`, never both: the format uses
    the presence of one to mean the absence of the other, and this parser keeps that rather
    than inventing a default weight for a hard constraint.
    """

    type: str
    """As written, parameters included: `MaxBlock(60,30)`."""

    name: str
    """The type without its parameters: `MaxBlock`."""

    parameters: tuple[int, ...]
    required: bool
    penalty: int | None
    classes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Student:
    id: int
    courses: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Optimization:
    """The four weights the competition's objective is made of."""

    time: int
    room: int
    distribution: int
    student: int


@dataclass(frozen=True, slots=True)
class Instance:
    name: str
    nr_days: int
    slots_per_day: int
    nr_weeks: int
    optimization: Optimization
    rooms: tuple[Room, ...]
    courses: tuple[Course, ...]
    distributions: tuple[Distribution, ...]
    students: tuple[Student, ...] = field(default_factory=tuple)

    @property
    def classes(self) -> tuple[Class, ...]:
        """Every class definition, flattened.

        The competition's own instance tables count classes this way, so the parser can be
        checked against an external oracle rather than against itself.
        """
        return tuple(
            klass
            for course in self.courses
            for config in course.configs
            for subpart in config.subparts
            for klass in subpart.classes
        )

    @property
    def needs_multiple_weeks(self) -> bool:
        """Whether any class runs in some weeks and not others.

        True for 30 of the 36 published instances — which is the finding that says Tessera's
        single repeating week is a real gap rather than a competition artefact.
        """
        return any(not t.is_every_week for k in self.classes for t in k.times)


def read(source: Path | bytes, name: str = "") -> Instance:
    """Parse one instance.

    Takes bytes as well as a path so a test can hold an instance inline, and so a cached
    download need not be written out before being read.
    """
    try:
        root = ET.fromstring(source) if isinstance(source, bytes) else ET.parse(source).getroot()
    except ET.ParseError as error:
        raise MalformedInstanceError(
            f"{name or source!r} is not well-formed XML: {error}"
        ) from error

    if root.tag != "problem":
        raise MalformedInstanceError(
            f"{name or source!r} has <{root.tag}> at its root, not <problem> — "
            "this does not look like an ITC-2019 instance"
        )

    nr_days = _int(root, "nrDays")
    nr_weeks = _int(root, "nrWeeks")

    return Instance(
        name=_text(root, "name"),
        nr_days=nr_days,
        slots_per_day=_int(root, "slotsPerDay"),
        nr_weeks=nr_weeks,
        optimization=_optimization(root),
        rooms=tuple(_room(r, nr_days, nr_weeks) for r in root.findall("./rooms/room")),
        courses=tuple(_course(c, nr_days, nr_weeks) for c in root.findall("./courses/course")),
        distributions=tuple(_distribution(d) for d in root.findall("./distributions/distribution")),
        students=tuple(_student(s) for s in root.findall("./students/student")),
    )


def _optimization(root: ET.Element) -> Optimization:
    found = root.find("./optimization")
    if found is None:
        raise MalformedInstanceError("the instance has no <optimization> weights")
    return Optimization(
        time=_int(found, "time"),
        room=_int(found, "room"),
        distribution=_int(found, "distribution"),
        student=_int(found, "student"),
    )


def _room(element: ET.Element, nr_days: int, nr_weeks: int) -> Room:
    return Room(
        id=_int(element, "id"),
        capacity=_int(element, "capacity"),
        travel=tuple(
            Travel(room=_int(t, "room"), value=_int(t, "value")) for t in element.findall("travel")
        ),
        unavailable=tuple(
            Unavailable(
                days=_mask(u, "days", nr_days),
                start=_int(u, "start"),
                length=_int(u, "length"),
                weeks=_mask(u, "weeks", nr_weeks),
            )
            for u in element.findall("unavailable")
        ),
    )


def _course(element: ET.Element, nr_days: int, nr_weeks: int) -> Course:
    return Course(
        id=_int(element, "id"),
        configs=tuple(
            Config(
                id=_int(c, "id"),
                subparts=tuple(
                    Subpart(
                        id=_int(s, "id"),
                        classes=tuple(_class(k, nr_days, nr_weeks) for k in s.findall("class")),
                    )
                    for s in c.findall("subpart")
                ),
            )
            for c in element.findall("config")
        ),
    )


def _class(element: ET.Element, nr_days: int, nr_weeks: int) -> Class:
    parent = element.get("parent")
    return Class(
        id=_int(element, "id"),
        limit=_int(element, "limit"),
        parent=int(parent) if parent is not None else None,
        # Absent means "a room is needed"; only the literal `false` disables it. Anything
        # else is a spelling this parser has not seen and will not guess at.
        needs_room=_needs_room(element),
        rooms=tuple(
            RoomOption(room=_int(r, "id"), penalty=_int(r, "penalty"))
            for r in element.findall("room")
        ),
        times=tuple(
            TimeOption(
                days=_mask(t, "days", nr_days),
                start=_int(t, "start"),
                length=_int(t, "length"),
                weeks=_mask(t, "weeks", nr_weeks),
                penalty=_int(t, "penalty"),
            )
            for t in element.findall("time")
        ),
    )


def _needs_room(element: ET.Element) -> bool:
    value = element.get("room")
    if value is None:
        return True
    if value == "false":
        return False
    raise MalformedInstanceError(
        f"class {element.get('id')} has room={value!r}; only 'false' or absent are understood"
    )


def _distribution(element: ET.Element) -> Distribution:
    written = _text(element, "type")
    matched = _TYPE.match(written)
    if matched is None:
        raise MalformedInstanceError(
            f"distribution type {written!r} is not a form this parser reads"
        )

    required = element.get("required")
    penalty = element.get("penalty")
    # Exactly one. The format expresses hard-versus-soft by which attribute is present, and
    # a parser that accepted both would have to invent a precedence the file does not state.
    if (required is None) == (penalty is None):
        raise MalformedInstanceError(
            f"distribution {written!r} has "
            f"{'both required and penalty' if required else 'neither required nor penalty'}"
        )

    args = matched.group("args")
    return Distribution(
        type=written,
        name=matched.group("name"),
        parameters=tuple(int(a) for a in args.split(",")) if args else (),
        required=required == "true",
        penalty=int(penalty) if penalty is not None else None,
        classes=tuple(_int(c, "id") for c in element.findall("class")),
    )


def _student(element: ET.Element) -> Student:
    return Student(
        id=_int(element, "id"),
        courses=tuple(_int(c, "id") for c in element.findall("course")),
    )


def _text(element: ET.Element, name: str) -> str:
    value = element.get(name)
    if value is None:
        raise MalformedInstanceError(f"<{element.tag}> has no {name!r}")
    return value


def _int(element: ET.Element, name: str) -> int:
    value = _text(element, name)
    try:
        return int(value)
    except ValueError as error:
        raise MalformedInstanceError(f"<{element.tag}> {name}={value!r} is not a number") from error


def _mask(element: ET.Element, name: str, expected: int) -> str:
    """A bitmask, checked against the length the instance declared.

    Length is the one thing worth checking here, and it is worth checking because it is the
    one thing that goes wrong silently: a `weeks` string one character short shifts every
    week it names, and the result is a plausible number in a report nobody can falsify.
    """
    value = _text(element, name)
    if len(value) != expected or set(value) - {"0", "1"}:
        raise MalformedInstanceError(
            f"<{element.tag}> {name}={value!r} is not {expected} binary digits"
        )
    return value
