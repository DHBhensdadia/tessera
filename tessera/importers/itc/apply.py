"""An instance, as much of it as Tessera can hold — and a ledger of the rest.

`format.py` reads the file; this decides what of it Tessera can represent. The two are
separate because a report that compared a mapped instance against itself would measure the
parser rather than the loss (D6).

**Nothing here writes anything.** `tessera.importers` may not import SQLAlchemy, which is what
lets a whole instance be checked before a single row exists — the same discipline the
spreadsheet importer works under (D4). `repository/imports.py` applies what this produces.

**Nothing here changes to make the numbers better.** D2 rules out reshaping `tessera/domain/`
to fit a competition, and D7 rules out synthesising structure an instance does not state. Both
were written before the numbers were known, which is the only time such a rule can be written
honestly. So the ledger below records real losses, and the losses are large: an ITC instance is
mostly *scheduling problem* — per-class time domains, penalties, alternative configurations —
and Tessera holds a *university*. What survives the crossing is the university part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import ceil

from tessera.domain import entities as d
from tessera.domain.constraints import ConstraintKind
from tessera.domain.time_grid import TimeGrid
from tessera.importers.itc.format import Instance

#: Granularities to try, finest first. Tessera's grid allows 5 to 120 minutes; nothing coarser
#: than an hour is worth offering, since it would round a 50-minute class to a full hour.
GRANULARITIES = (5, 10, 15, 20, 30, 60)

#: `TimeGrid.slots_per_day` is capped here by the domain, and D2 says that cap does not move
#: for a benchmark. It is what forces every instance onto a coarser grid than it was written
#: on: ITC uses 288 five-minute slots, midnight to midnight, in all 36.
MAX_SLOTS_PER_DAY = 96

#: One ITC slot, in minutes. Constant across the whole published set.
ITC_SLOT_MINUTES = 5


class Fate(StrEnum):
    """What happened to one kind of thing on the way in."""

    CARRIED = "carried"
    """Held exactly. Reading it back out would give the same answer."""

    APPROXIMATED = "approximated"
    """Held, but changed. A time moved to a coarser grid is still that class at roughly
    that hour; it is not the same instant."""

    DROPPED = "dropped"
    """Not held at all. Named with a count, never silently absent."""


@dataclass(frozen=True)
class Entry:
    """One line of the ledger: what, how many, what happened, and why."""

    what: str
    count: int
    fate: Fate
    because: str = ""


@dataclass(frozen=True)
class Ledger:
    """Everything the mapping did, in numbers a reader can check against the file.

    Part 3 turns these into the committed fidelity report. It lives here rather than there
    because it is a record of what the mapping did, and only the mapping knows.
    """

    instance: str
    entries: tuple[Entry, ...] = ()

    def of(self, fate: Fate) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.fate is fate)

    def total(self, fate: Fate) -> int:
        return sum(e.count for e in self.of(fate))

    @property
    def is_lossless(self) -> bool:
        """Whether anything at all was lost.

        Expected to be false for every published instance. A method rather than a comment
        because part 3 has to state it per instance, and an implementation that quietly
        returned true for a mapping that dropped 52,254 classes is the failure this whole
        phase is arranged to prevent.
        """
        return not (self.of(Fate.APPROXIMATED) or self.of(Fate.DROPPED))


@dataclass(frozen=True)
class Grid:
    """The teaching week an instance's times will be held in, and how to get there.

    Not a `TimeGrid` yet — that is the domain object, and this also carries the arithmetic
    for moving an ITC slot onto it, which the domain has no business knowing.
    """

    days: int
    slots_per_day: int
    slot_minutes: int
    day_start_minute: int

    @classmethod
    def for_(cls, instance: Instance) -> Grid:
        """The finest grid that holds this instance inside Tessera's 96-slot ceiling.

        Finest, not simply "one that fits": a fixed 15-minute grid would fit all 36, but 25
        of them fit at 10 minutes and holding those more precisely costs nothing. The
        granularity is therefore a property of the instance, and the report says which one
        each got.

        The day is narrowed to the hours actually used, which is what buys the precision —
        ITC's day runs midnight to midnight, and at five-minute slots that is 288 of them,
        but no instance teaches across more than 22 hours and most use about 14.
        """
        first, last = _window(instance)
        for minutes in GRANULARITIES:
            start = (first * ITC_SLOT_MINUTES // minutes) * minutes
            slots = ceil((last * ITC_SLOT_MINUTES - start) / minutes)
            if slots <= MAX_SLOTS_PER_DAY:
                return cls(
                    days=instance.nr_days,
                    slots_per_day=slots,
                    slot_minutes=minutes,
                    day_start_minute=start,
                )
        raise AssertionError(  # pragma: no cover - unreachable for a 24-hour day
            f"{instance.name} does not fit even at {GRANULARITIES[-1]}-minute slots"
        )

    @property
    def is_exact(self) -> bool:
        """Whether this grid can hold ITC's five-minute times without rounding at all.

        False for every published instance — none fits inside 96 slots at five minutes —
        so it exists to be *stated* rather than assumed, and to keep the mapping honest if
        a finer instance ever appears.
        """
        return self.slot_minutes == ITC_SLOT_MINUTES

    def slot_of_day(self, itc_slot: int) -> int:
        """An ITC slot index onto this grid, rounded down to the slot containing it."""
        return (itc_slot * ITC_SLOT_MINUTES - self.day_start_minute) // self.slot_minutes

    def covers(self, itc_slot: int, length: int) -> range:
        """Every slot of the day a class occupies, rounded outward.

        Outward on purpose. Rounding a 50-minute class down onto a 15-minute grid would hand
        the solver a room for the last five minutes of a class still in it, and the resulting
        timetable would be wrong in a way no test of Tessera's would catch — it would be
        perfectly consistent with the data it was given.
        """
        first = (itc_slot * ITC_SLOT_MINUTES - self.day_start_minute) // self.slot_minutes
        after = ceil(
            ((itc_slot + length) * ITC_SLOT_MINUTES - self.day_start_minute) / self.slot_minutes
        )
        return range(first, max(after, first + 1))

    def lands_exactly(self, itc_slot: int, length: int) -> bool:
        """Whether this time survives the move unchanged."""
        offset = itc_slot * ITC_SLOT_MINUTES - self.day_start_minute
        return (
            offset % self.slot_minutes == 0 and (length * ITC_SLOT_MINUTES) % self.slot_minutes == 0
        )

    def to_domain(self, institution_id: int | None = None) -> TimeGrid:
        return TimeGrid(
            institution_id=institution_id,  # type: ignore[arg-type]
            name="ITC-2019",
            days=self.days,
            slots_per_day=self.slots_per_day,
            slot_minutes=self.slot_minutes,
            day_start_minute=self.day_start_minute,
        )


def _window(instance: Instance) -> tuple[int, int]:
    """The first and last ITC slot any class can be taught in.

    **Class times only, deliberately.** Room closures were included here first, and it was
    wrong twice over. Some instances close rooms from midnight, which widened the day to the
    full 24 hours and forced every instance onto 15-minute slots — `bet-sum18` teaches
    between 08:00 and 16:50 and was being given a grid that started at midnight. And a
    closure outside the teaching day forbids nothing, because nothing can be scheduled there
    to forbid: the part that matters is the part overlapping the day, which `_closures`
    keeps.

    So the day is the day classes are taught in, and closures are clipped to it. That is
    what buys 25 of the 36 instances a 10-minute grid instead of a 15-minute one.
    """
    starts = [t.start for k in instance.classes for t in k.times]
    ends = [t.start + t.length for k in instance.classes for t in k.times]
    return min(starts), max(ends)


@dataclass(frozen=True)
class Fit:
    """How well a teaching week would hold an instance's class times.

    A measurement, not a ledger entry. Every class is dropped, so nothing here is *carried*
    anywhere — but the number still says something worth saying: whether Tessera's grid could
    represent these times at all, if the classes themselves ever became representable.

    Kept apart from the ledger precisely because the two are easy to conflate, and conflating
    them puts a million things in the "carried" column that are not in the project.
    """

    exact: int
    moved: int

    @property
    def total(self) -> int:
        return self.exact + self.moved


@dataclass(frozen=True)
class Closure:
    """A room, and the slots of the week it cannot be used in."""

    room: str
    slots: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class Mapped:
    """An instance as Tessera would hold it, plus what that cost.

    Names rather than ids throughout, because nothing here has been written yet and ids do
    not exist until it has. The applier resolves them as it goes, exactly as the spreadsheet
    importer resolves a building name to a building.
    """

    instance: str
    grid: Grid
    institution: str
    term: d.Term
    rooms: tuple[d.Room, ...] = ()
    courses: tuple[d.Course, ...] = ()
    offerings: tuple[str, ...] = ()
    closures: tuple[Closure, ...] = ()
    fit: Fit = Fit(exact=0, moved=0)
    ledger: Ledger = field(default_factory=lambda: Ledger(instance=""))


def room_name(room_id: int) -> str:
    """ITC rooms have an id and a capacity, and no name.

    Naming them after the id is the only option that stays reversible: `Room 12` can be
    traced back to `<room id="12">` in the file, which matters when a fidelity number has
    to be checked by hand.
    """
    return f"Room {room_id}"


def course_code(course_id: int) -> str:
    """Likewise for courses — an id, no code, no title."""
    return f"C{course_id}"


def mapped(instance: Instance) -> Mapped:
    """What Tessera can hold of this instance, and a ledger of everything else."""
    grid = Grid.for_(instance)
    entries: list[Entry] = []

    rooms = tuple(d.Room(name=room_name(r.id), capacity=r.capacity) for r in instance.rooms)
    courses = tuple(
        d.Course(code=course_code(c.id), name=course_code(c.id)) for c in instance.courses
    )
    closures, closure_entries = _closures(instance, grid)

    entries.append(Entry("rooms", len(rooms), Fate.CARRIED))
    entries.append(Entry("courses", len(courses), Fate.CARRIED))
    entries.append(Entry("offerings", len(courses), Fate.CARRIED))
    entries.extend(closure_entries)
    entries.extend(_grid_entries(instance))
    entries.extend(_dropped(instance))

    return Mapped(
        instance=instance.name,
        grid=grid,
        institution=instance.name,
        term=d.Term(academic_year="ITC-2019", name=instance.name),
        rooms=rooms,
        courses=courses,
        offerings=tuple(c.code for c in courses),
        closures=closures,
        fit=_fit(instance, grid),
        ledger=Ledger(instance=instance.name, entries=tuple(entries)),
    )


def _grid_entries(instance: Instance) -> list[Entry]:
    """What the teaching week itself carries.

    **Not the class times.** They belong to classes, every class is dropped, and a ledger
    that counted a time option as *carried* would be claiming something is in the project
    that is not there — the exact self-flattery this report exists to avoid. How well the
    grid *would* hold them is a property of the grid, measured by `Grid.fit`, and reported
    where it is true rather than counted where it is not.
    """
    return [
        Entry(
            "teaching days",
            instance.nr_days,
            Fate.CARRIED,
            f"{instance.nr_days} days, as written",
        )
    ]


def _fit(instance: Instance, grid: Grid) -> Fit:
    """How many of the instance's class times land on its grid unchanged."""
    times = [t for k in instance.classes for t in k.times]
    exact = sum(1 for t in times if grid.lands_exactly(t.start, t.length))
    return Fit(exact=exact, moved=len(times) - exact)


def _closures(instance: Instance, grid: Grid) -> tuple[tuple[Closure, ...], list[Entry]]:
    """Room closures, for the ones that apply to the whole term.

    A closure that applies to some weeks and not others is **dropped rather than widened**.
    Widening it would block a room in weeks the instance says it is free — which is not a
    lossy import but a wrong one, and the kind of wrongness that produces a plausible
    timetable nobody can falsify.

    Closures are clipped to the teaching day. The part outside it forbids nothing, because
    no class can be scheduled there in the first place, so a closure lying entirely outside
    is counted apart rather than reported as a loss it is not.
    """
    carried: list[Closure] = []
    partial = vacuous = rounded = 0
    for room in instance.rooms:
        for window in room.unavailable:
            if set(window.weeks) != {"1"}:
                partial += 1
                continue
            within = [
                slot
                for slot in grid.covers(window.start, window.length)
                if 0 <= slot < grid.slots_per_day
            ]
            if not within:
                vacuous += 1
                continue
            if not grid.lands_exactly(window.start, window.length):
                rounded += 1
            carried.append(
                Closure(
                    room=room_name(room.id),
                    slots=tuple(
                        sorted(
                            day * grid.slots_per_day + slot
                            for day, taught in enumerate(window.days)
                            if taught == "1"
                            for slot in within
                        )
                    ),
                    reason="ITC-2019",
                )
            )

    entries = []
    if exact := len(carried) - rounded:
        entries.append(Entry("room closures", exact, Fate.CARRIED))
    if rounded:
        entries.append(
            Entry(
                "room closures",
                rounded,
                Fate.APPROXIMATED,
                "widened to the coarser grid the instance had to be given; a closure "
                "rounded inward would free a room that is shut",
            )
        )
    if vacuous:
        entries.append(
            Entry(
                "room closures outside teaching hours",
                vacuous,
                Fate.CARRIED,
                "fall outside the day classes are taught in, so they forbid nothing",
            )
        )
    if partial:
        entries.append(
            Entry(
                "room closures",
                partial,
                Fate.DROPPED,
                "apply to some weeks only; blocking every week would forbid a room the "
                "instance says is free",
            )
        )
    return tuple(carried), entries


def _dropped(instance: Instance) -> list[Entry]:
    """Everything Tessera has nowhere to put, named with a count.

    The list is long, and it is meant to be read rather than skimmed: this is the part of
    the phase that is allowed to come out badly, and a reader who cannot check a number
    against the file is being asked to take a claim on trust.
    """
    entries: list[Entry] = []

    configs = sum(len(c.configs) for c in instance.courses)
    if alternatives := sum(1 for c in instance.courses if len(c.configs) > 1):
        entries.append(
            Entry(
                "courses with alternative configurations",
                alternatives,
                Fate.DROPPED,
                "a course offered as competing whole structures; Tessera has one structure "
                "per offering",
            )
        )
    entries.append(
        Entry(
            "configurations",
            configs,
            Fate.DROPPED,
            "no counterpart: an offering in Tessera is not one of several ways to take a course",
        )
    )

    subparts = sum(len(s.subparts) for c in instance.courses for s in c.configs)
    entries.append(
        Entry(
            "subparts",
            subparts,
            Fate.DROPPED,
            "the nearest thing is a session template, which cannot be built without student "
            "groups the instance does not state",
        )
    )

    classes = instance.classes
    entries.append(
        Entry(
            "classes",
            len(classes),
            Fate.DROPPED,
            "a session template must be taught to at least one group; ITC states individual "
            "student enrolments instead, and inventing a programme tree to hold them would "
            "be reporting a fidelity the invention created",
        )
    )
    if parented := sum(1 for k in classes if k.parent is not None):
        entries.append(
            Entry(
                "parent-child class links",
                parented,
                Fate.DROPPED,
                "'a student in this class must also attend that one' — no counterpart",
            )
        )
    if roomless := sum(1 for k in classes if not k.needs_room):
        entries.append(
            Entry(
                "classes needing no room",
                roomless,
                Fate.DROPPED,
                "dropped with the classes; Tessera has no way to say a session needs no room",
            )
        )
    entries.append(
        Entry(
            "per-class room options",
            sum(len(k.rooms) for k in classes),
            Fate.DROPPED,
            "an explicit ranked list of rooms per class; Tessera derives eligibility from "
            "capacity and features",
        )
    )
    entries.append(
        Entry(
            "class time options",
            sum(len(k.times) for k in classes),
            Fate.DROPPED,
            "dropped with the classes they belong to; see the grid section for how well "
            "the teaching week would have held them",
        )
    )
    if penalised := sum(1 for k in classes for t in k.times if t.penalty):
        entries.append(
            Entry(
                "penalties on time options",
                penalised,
                Fate.DROPPED,
                "a cost per alternative; Tessera weights a rule, not an individual choice",
            )
        )

    if varied := sum(1 for k in classes for t in k.times if not t.is_every_week):
        entries.append(
            Entry(
                "time options confined to some weeks",
                varied,
                Fate.DROPPED,
                "Tessera's week pattern offers every week, odd weeks or even weeks; these "
                "are arbitrary masks over the term",
            )
        )

    if travel := sum(len(r.travel) for r in instance.rooms):
        entries.append(
            Entry(
                "room-to-room travel times",
                travel,
                Fate.DROPPED,
                "a number of slots between two rooms; Tessera has buildings and a "
                "preference against moving between them, which is qualitative",
            )
        )

    if instance.students:
        entries.append(
            Entry(
                "students",
                len(instance.students),
                Fate.DROPPED,
                "individuals with course lists; a Tessera cohort must name the structural "
                "groups it draws from, and an ITC instance has no programme tree to draw on",
            )
        )

    entries.extend(_distributions(instance))
    entries.append(
        Entry(
            "objective weights",
            4,
            Fate.DROPPED,
            "time, room, distribution and student, weighting the competition's own "
            "objective; Tessera weights each rule separately",
        )
    )
    return entries


#: ITC distribution types against Tessera's constraint kinds.
#:
#: Typed against the real `ConstraintKind` rather than against strings, so a counterpart that
#: does not exist cannot be named. The report is read as a statement about Tessera's model;
#: a plausible-looking `SAME_WEEK` in it that no code has ever heard of would be the worst
#: kind of error here — checkable only by someone who already knew the answer.
#:
#: The ones marked `None` are not oversights. Each was checked, and the report is more useful
#: for naming them than a mapping invented to shorten the list would be.
COUNTERPARTS: dict[str, ConstraintKind | None] = {
    "SameStart": None,
    "SameTime": ConstraintKind.SAME_TIME,
    "DifferentTime": None,
    "SameDays": ConstraintKind.SAME_DAY,
    "DifferentDays": ConstraintKind.DIFFERENT_DAY,
    "SameWeeks": None,
    "DifferentWeeks": None,
    "SameRoom": ConstraintKind.SAME_ROOM,
    "DifferentRoom": None,
    "Overlap": None,
    "NotOverlap": ConstraintKind.NOT_OVERLAP,
    "SameAttendees": None,
    "Precedence": ConstraintKind.PRECEDES,
    "WorkDay": None,
    "MinGap": ConstraintKind.MIN_GAP,
    "MaxDays": None,
    "MaxDayLoad": None,
    "MaxBreaks": None,
    "MaxBlock": ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
}


def _distributions(instance: Instance) -> list[Entry]:
    """The distribution constraints, by type, and why none of them is carried yet.

    Even the ones with a counterpart are dropped, and the reason is not the constraint but
    what it refers to: every ITC distribution names classes, and no class was carried. A
    `SameRoom` over two classes that do not exist is not a constraint, and writing it as
    one would be the report flattering itself.
    """
    counted: dict[str, int] = {}
    for distribution in instance.distributions:
        counted[distribution.name] = counted.get(distribution.name, 0) + 1

    entries = []
    for name, count in sorted(counted.items(), key=lambda item: -item[1]):
        counterpart = COUNTERPARTS.get(name)
        entries.append(
            Entry(
                f"distribution: {name}",
                count,
                Fate.DROPPED,
                f"Tessera has {counterpart.name}, but it would refer to classes that were "
                "themselves dropped"
                if counterpart
                else "no counterpart in Tessera",
            )
        )
    return entries
