"""The score, written a second time — as arithmetic CP-SAT can minimise.

**This is deliberately a second implementation.** 4.1's `rules.py` already computes what a
timetable costs, and its docstring says why this exists anyway: *"Phase 0.1 got zero cost
mismatches across 21 instances precisely because the checker and the model were separate
readings."* Two readings that agree are evidence. One reading agreeing with itself is not.

So `rules.py` stays the authority for the score of a finished timetable, this expresses the
same sixteen rules as linear arithmetic over the decision variables, and
`tests/solver/test_agreement.py` asserts the two produce **the same integer**. That test is
the phase's exit criterion, and it is stronger than "raising a weight reduces that violation
class" — which can pass while both implementations are wrong in the same direction.

**Every term is clamped at zero.** Phase 0.1's first optimising run returned cost 5 with a
lower bound of **-7**, because room stability was written `sum(uses_room) - 1` and a course in
one room contributed -0. An all-penalty objective cannot be negative; a term that can go
negative lets CP-SAT "improve" the objective past the bottom, and the bound it then derives is
unsound. That solver burned the full 60 s unable to prove what it had already found at 3.41 s.
Here every unit variable is declared over a non-negative domain *and* clamped by
`add_max_equality`, so it is impossible by construction rather than by care.

All sixteen kinds have a term. A partial objective would silently ignore whichever slider a
user moved, which is the worst kind of interface defect because it looks like it works — so a
kind without one is refused rather than skipped.

**Weights come from the constraints, never from constants.** 2.8 put a weight on `Constraint`
and 3.5 put sliders on the rules screen; an objective with numbers baked in would make those
sliders decorative, which is the worst kind of interface defect because it looks like it
works. A *hard* constraint has `effective_weight` 0 and is not priced at all — it is pinned to
zero units, refused rather than traded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, pairwise, permutations
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from tessera.domain.constraints import Constraint, ConstraintKind, TargetKind
from tessera.domain.ids import InstructorId, SessionId
from tessera.domain.time_grid import Slot
from tessera.domain.validation import Snapshot
from tessera.solver.model import Model

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

#: Stands in for a room with no building. A real `building_id` is at least 1, so this cannot
#: collide with one — and "unassigned" has to be a value rather than a gap, because two
#: sessions in two unassigned rooms are in the same place as far as this rule is concerned.
NOWHERE = 0


class NotScorableError(NotImplementedError):
    """A rule with no objective term, met in a term the solver was asked to score.

    All sixteen kinds have one, so this fires only if a seventeenth is added to the enum
    without one — the discipline `_named` is held to in the invariants (#193), and the reason
    `SPECS` is checked against `ConstraintKind` rather than trusted.

    Loud on purpose. The quiet alternative — score the kinds we have and omit the rest —
    produces a timetable optimised against a rulebook nobody wrote down, and a penalty that
    does not answer for the difference. An institution sets "minimise gaps", the term is
    missing, and the number reported is confidently wrong with nothing to say so.
    """


#: Anything able to read a variable's value out of a finished search.
#:
#: `CpSolver` after `solve()` returns, and `CpSolverSolutionCallback` *during* one — the two
#: have the same `value()` and are unrelated classes. 4.7's stream reads the score from inside
#: the callback, which is the only place the score exists while an unrestricted attempt is
#: still running, and annotating that as `CpSolver` would have been false.
type Values = cp_model.CpSolver | cp_model.CpSolverSolutionCallback


@dataclass(frozen=True)
class Objective:
    """What the model minimises, and how to read the result back out.

    `by_kind` is per *kind* rather than per constraint, matching `Report.penalty_breakdown`:
    an institution with three narrowed `MIN_GAP` rules wants to know what gaps cost it, not
    what rule 14 cost it. Reporting them the same way is what makes the two comparable at all.

    Keyed by the kind's **name** rather than by `ConstraintKind`, because 4.5's benchmark
    minimises CB-CTT's four soft constraints through this same object and they are not Tessera
    rules. `ConstraintKind` is a `StrEnum`, so for the sixteen this changes neither the keys
    nor the order they sort in.
    """

    total: cp_model.IntVar
    by_kind: dict[str, cp_model.IntVar]

    units: tuple[cp_model.IntVar, ...] = ()
    """Every violation count the terms produced, hard ones included.

    Kept so a test can walk them and assert what D2 claims: not one has a domain that
    reaches below zero. A guarantee nobody checks is a comment."""

    def floors(self) -> tuple[int, ...]:
        """The lowest value each violation count may take. Every one of them is zero."""
        return tuple(bounds(unit)[0] for unit in self.units)

    def penalty(self, solver: Values) -> int:
        return int(solver.value(self.total))

    def breakdown(self, solver: Values) -> dict[str, int]:
        """The penalty by rule, largest first — `Report.penalty_breakdown`'s shape exactly.

        Zero-cost kinds are dropped for the same reason the validator drops them: a rule an
        institution set and never broke is not a line in a report about what went wrong.
        """
        scored = {kind: int(solver.value(var)) for kind, var in self.by_kind.items()}
        return dict(sorted(((k, v) for k, v in scored.items() if v), key=lambda item: -item[1]))


@dataclass
class Terms:
    """The scaffolding the sixteen rules are written against.

    Its job is to make a rule read like the sentence it enforces. `SAME_DAY` should be "count
    the distinct days and subtract one", not thirty lines of channelling — so the channelling
    lives here, is built once per session, and is shared by every rule that asks for it.
    """

    model: Model
    snapshot: Snapshot

    _day: dict[SessionId, cp_model.IntVar] = field(default_factory=dict)
    _hour: dict[SessionId, cp_model.IntVar] = field(default_factory=dict)
    _is: dict[tuple[SessionId, str, int], cp_model.IntVar] = field(default_factory=dict)

    @property
    def cp(self) -> cp_model.CpModel:
        return self.model.cp

    # -- what a rule is about ----------------------------------------------------

    def targets(self, constraint: Constraint) -> list[SessionId]:
        """The sessions this rule names that the term actually contains, in id order.

        A rule may name a session that is not here; the validator's `Lens.placed` drops it
        silently and so does this. Order matters for `PRECEDES` alone, and ascending id is
        the order it reads — see that rule for why that is a gap rather than a design.
        """
        return sorted(s for s in constraint.target_ids if s in self.model.starts)

    def pairs(self, constraint: Constraint) -> Iterator[tuple[SessionId, SessionId]]:
        """Every unordered pair, once — `rules._pairs`, which sorts by id and combines."""
        yield from combinations(self.targets(constraint), 2)

    def duration(self, session_id: SessionId) -> int:
        return self.snapshot.sessions[session_id].duration_slots

    # -- the channelling ---------------------------------------------------------

    def day(self, session_id: SessionId) -> cp_model.IntVar:
        """Which day this session starts on.

        Division rather than a table over the start's whole domain: `slots_per_day` is a
        constant, so `add_division_equality` is exact and costs one constraint where a table
        would cost up to 672 tuples per session.
        """
        if session_id not in self._day:
            var = self._over(self.days(session_id), f"day[{session_id}]")
            self.cp.add_division_equality(
                var, self.model.starts[session_id], self.snapshot.grid.slots_per_day
            )
            self._day[session_id] = var
        return self._day[session_id]

    def hour(self, session_id: SessionId) -> cp_model.IntVar:
        """Which hour *of the day* this session starts at.

        Slot-of-day, not the week-absolute slot, because that is what `SAME_TIME` means:
        same-day is a rule of its own, and collapsing the two would make `SAME_DAY`
        unreachable.
        """
        if session_id not in self._hour:
            var = self._over(self.hours(session_id), f"hour[{session_id}]")
            self.cp.add_modulo_equality(
                var, self.model.starts[session_id], self.snapshot.grid.slots_per_day
            )
            self._hour[session_id] = var
        return self._hour[session_id]

    def days(self, session_id: SessionId) -> tuple[int, ...]:
        """The days this session could start on, given where it may legally start."""
        per_day = self.snapshot.grid.slots_per_day
        return tuple(sorted({slot // per_day for slot in self.model.legal[session_id]}))

    def hours(self, session_id: SessionId) -> tuple[int, ...]:
        per_day = self.snapshot.grid.slots_per_day
        return tuple(sorted({slot % per_day for slot in self.model.legal[session_id]}))

    def on_day(self, session_id: SessionId) -> dict[int, cp_model.IntVar]:
        """One boolean per day this session could be on, true for the day it is on."""
        return {
            day: self._equals(session_id, "day", self.day(session_id), day)
            for day in self.days(session_id)
        }

    def at_hour(self, session_id: SessionId) -> dict[int, cp_model.IntVar]:
        return {
            hour: self._equals(session_id, "hour", self.hour(session_id), hour)
            for hour in self.hours(session_id)
        }

    def in_room(self, session_id: SessionId) -> dict[int, cp_model.IntVar]:
        """One boolean per room this session could be in — 4.2's, not a second set.

        The presence literals already exist and `add_exactly_one` already makes exactly one
        of them true. Building a parallel set would be two answers to "which room is this
        in", which is the drift Decision #5 is about.
        """
        return {c.room: c.present for c in self.model.candidates[session_id]}

    # -- the shapes the rules are built from --------------------------------------

    def distinct(
        self,
        constraint: Constraint,
        targets: Sequence[SessionId],
        choices: Callable[[SessionId], Mapping[int, cp_model.IntVar]],
    ) -> list[cp_model.IntVar]:
        """How many different values these sessions take, less one. `rules._agree_on`.

        Reported as one count for the whole set rather than one per session that differs,
        which is what the validator does and for the reason it gives: a person told four
        times that four sessions disagree has been told one thing.

        Fewer than two sessions is silence on both sides — one session cannot disagree with
        itself, and the validator's `len(placed) > 1` says so.

        `targets` is passed rather than read from the constraint, because the same shape
        answers two different questions: three sessions a rule names must share a room, and
        every session of a course should. `PREFER_ROOM_STABILITY` is the second, over a
        subject's sessions rather than over named ones.
        """
        if len(targets) < 2:
            return []

        taken = [choices(session_id) for session_id in targets]
        values = sorted({value for choice in taken for value in choice})
        used = []
        for value in values:
            flag = self.cp.new_bool_var(f"used[{constraint.kind.value},{value}]")
            self.cp.add_max_equality(flag, [c[value] for c in taken if value in c])
            used.append(flag)

        return [self.count(constraint, sum(used) - 1, len(values) - 1)]

    def count(self, constraint: Constraint, of: cp_model.LinearExprT, most: int) -> cp_model.IntVar:
        """One violation count: `max(of, 0)`, over a domain that cannot reach below zero.

        Both halves of D2, and each covers a different failure. The **domain** makes a
        negative term unrepresentable, so 0.1's unsound bound cannot be written here at all.
        The **clamp** makes the value right when the expression itself would go negative —
        without it the model would simply be infeasible, which is a confusing way to report
        an arithmetic slip.
        """
        units = self.cp.new_int_var(0, max(most, 0), f"units[{constraint.kind.value}]")
        self.cp.add_max_equality(units, [of, 0])
        return units

    def apart(self, first: SessionId, second: SessionId, distance: int) -> cp_model.IntVar:
        """True when `second` starts at least `distance` slots after `first` finishes."""
        gap = self.model.starts[second] - self.model.starts[first] - self.duration(first)
        flag = self.cp.new_bool_var(f"apart[{first},{second},{distance}]")
        self.cp.add(gap >= distance).only_enforce_if(flag)
        self.cp.add(gap < distance).only_enforce_if(~flag)
        return flag

    def too_close(self, first: SessionId, second: SessionId, distance: int) -> cp_model.IntVar:
        """True when neither of these leaves `distance` slots clear of the other.

        Which one comes first is a decision variable, so the rule is written as *neither
        order works* rather than by sorting — the validator sorts by start slot, and a model
        cannot sort what it has not yet chosen.

        The subtraction is exact because the two cannot both hold: adding the two
        inequalities gives `0 >= duration(first) + duration(second) + 2 x distance`, and a
        session lasts at least one slot.
        """
        forward = self.apart(first, second, distance)
        backward = self.apart(second, first, distance)
        flag = self.cp.new_bool_var(f"close[{first},{second},{distance}]")
        self.cp.add(flag == 1 - forward - backward)
        return flag

    def same_day(self, first: SessionId, second: SessionId) -> cp_model.IntVar:
        flag = self.cp.new_bool_var(f"sameday[{first},{second}]")
        self.cp.add(self.day(first) == self.day(second)).only_enforce_if(flag)
        self.cp.add(self.day(first) != self.day(second)).only_enforce_if(~flag)
        return flag

    # -- what a subject-scoped rule is about -----------------------------------------

    def subjects(
        self, constraint: Constraint, kind: TargetKind
    ) -> Iterator[tuple[int, list[SessionId]]]:
        """Each instructor, group or course this preference covers, and what they teach.

        `rules._per_subject`, and the two awkward parts of it are deliberate rather than
        incidental.

        **A narrowed rule that names nothing of this kind covers nobody**, not everybody. The
        four rules applying to both instructors and groups ask for each in turn, and falling
        back to "everyone" per kind meant a rule aimed at one instructor also charged every
        group in the term — the exact opposite of narrowing, and silent.

        **Groups are indexed by leaf**, because that is how `Snapshot` relates them. A rule
        narrowed to a parent group therefore covers nothing, which mirrors the validator
        exactly; whether it *should* is a question for the backlog, not for a term that has
        to agree with it.
        """
        index: dict[int, list[SessionId]] = {
            TargetKind.INSTRUCTOR: self.snapshot.sessions_of_instructor,
            TargetKind.GROUP: self.snapshot.sessions_of_group,
            TargetKind.COURSE: self.snapshot.sessions_of_course,
        }[kind]  # type: ignore[assignment]

        named = self.snapshot.subjects_named_by(constraint, kind)
        if constraint.targets and not named:
            return
        for subject in named or tuple(sorted(index)):
            # Index order, not sorted: MINIMISE_BUILDING_CHANGES compares adjacent sessions
            # in a day, and the validator's sort on start hour is stable — so two sessions at
            # one hour keep the order they are indexed in, and this has to be that order.
            taught = [s for s in index.get(subject, []) if s in self.model.starts]
            if taught:
                yield subject, taught

    def people(self, constraint: Constraint) -> Iterator[tuple[int, list[SessionId]]]:
        """Instructors and groups together, for the four kinds that apply to both."""
        yield from self.subjects(constraint, TargetKind.INSTRUCTOR)
        yield from self.subjects(constraint, TargetKind.GROUP)

    def week(self) -> Iterator[tuple[int, range]]:
        """Each day, and the slots in it."""
        per_day = self.snapshot.grid.slots_per_day
        for day in range(self.snapshot.grid.days):
            yield day, range(day * per_day, (day + 1) * per_day)

    # -- being busy at an hour, which is what the day-shaped rules count ---------------

    def at(self, session_id: SessionId) -> dict[Slot, cp_model.IntVar]:
        """One boolean per hour this session could begin at, true for the one it does.

        The channelling the whole of part 2 rests on. Exactly one is true, by reification
        against the start variable — nothing has to say so separately.
        """
        return {
            slot: self._equals(session_id, "start", self.model.starts[session_id], slot)
            for slot in self.model.legal[session_id]
        }

    def busy(self, session_id: SessionId, slot: Slot) -> cp_model.IntVar | None:
        """True when this session is being taught at this hour. `None` when it never could.

        Teaching time, not room occupancy: a room's turnaround is the room's, and a rule
        about somebody's day is about when they are teaching or being taught (#190).

        `None` rather than a variable fixed at zero, so a rule can leave out an hour it can
        say nothing about instead of building a network of constants around it.
        """
        key = (session_id, "busy", slot)
        if key not in self._is:
            duration = self.duration(session_id)
            covering = [
                begin for begin in self.model.legal[session_id] if begin <= slot < begin + duration
            ]
            if not covering:
                return None
            starts = self.at(session_id)
            self._is[key] = self.any_of(
                f"busy[{session_id},{slot}]", [starts[begin] for begin in covering]
            )
        return self._is[key]

    def busy_of(self, sessions: Sequence[SessionId], slot: Slot) -> cp_model.IntVar | None:
        """True when a subject is occupied at this hour by any of these sessions.

        A plain OR is exact because a subject's sessions cannot overlap — that is
        `instructor_not_double_booked` and `group_not_double_booked`, already constraints in
        the model rather than hopes about it.
        """
        found = [busy for s in sessions if (busy := self.busy(s, slot)) is not None]
        if not found:
            return None
        if len(found) == 1:
            return found[0]
        return self.any_of(f"busy[{slot}]", found)

    def in_building(self, session_id: SessionId) -> dict[int, cp_model.IntVar]:
        """One boolean per building this session could be in, true for the one it is.

        A room with no building is its own answer rather than an absence: two sessions in two
        unassigned rooms have not moved between buildings, and the validator agrees because
        `None == None`.
        """
        by_building: dict[int, list[cp_model.IntVar]] = {}
        for candidate in self.model.candidates[session_id]:
            room = self.snapshot.rooms[candidate.room]
            where = room.building_id if room.building_id is not None else NOWHERE
            by_building.setdefault(where, []).append(candidate.present)
        return {
            where: self.any_of(f"bldg[{session_id},{where}]", present)
            for where, present in sorted(by_building.items())
        }

    # -- the shapes the day-scoped rules are built from --------------------------------

    def gaps(self, constraint: Constraint, kind: TargetKind) -> list[cp_model.IntVar]:
        """Idle hours between the first and last session of a day. `rules._gaps`.

        Breaks do not count. A lunch hour in the middle of a day is not somebody waiting
        through it — it is the timetable working — and charging for it would penalise every
        full day equally and tell an institution nothing.

        An hour is idle when the subject is free at it *and* busy somewhere earlier in the
        day *and* busy somewhere later. Those two are running ORs built left to right and
        right to left, so the whole day costs a handful of variables per hour rather than a
        pair of ORs per hour over every other hour.
        """
        idle: list[cp_model.IntVar] = []
        for subject, taught in self.subjects(constraint, kind):
            for day, slots in self.week():
                hours = list(slots)
                busy = {slot: self.busy_of(taught, slot) for slot in hours}
                if sum(busy[slot] is not None for slot in hours) < 2:
                    continue

                where = f"{kind.value[0]}{subject}d{day}"
                earlier = self._running(busy, hours, f"upto[{where}]")
                later = self._running(busy, hours[::-1], f"from[{where}]")

                for position, slot in enumerate(hours):
                    if self.snapshot.grid.is_break(slot):
                        continue
                    before = earlier.get(hours[position - 1]) if position else None
                    after = later.get(hours[position + 1]) if position + 1 < len(hours) else None
                    if before is None or after is None:
                        continue
                    free = busy[slot]
                    idle.append(
                        self.all_of(
                            f"idle[{where}@{slot}]",
                            [before, after] if free is None else [before, after, ~free],
                        )
                    )
        return idle

    def _running(
        self,
        busy: Mapping[Slot, cp_model.IntVar | None],
        order: Sequence[Slot],
        name: str,
    ) -> dict[Slot, cp_model.IntVar]:
        """ "Busy at or before this hour", accumulated in the order given.

        Two literals per hour rather than a fresh OR over everything seen so far, which is
        the difference between a linear model and a quadratic one on a rule that applies to
        every group in the term.
        """
        carried: cp_model.IntVar | None = None
        seen: dict[Slot, cp_model.IntVar] = {}
        for slot in order:
            here = busy[slot]
            if here is not None:
                carried = (
                    here if carried is None else self.any_of(f"{name}@{slot}", [carried, here])
                )
            if carried is not None:
                seen[slot] = carried
        return seen

    def moves(self, constraint: Constraint) -> list[cp_model.IntVar]:
        """Changes of building between one session and the next one that day.

        **Over sessions, not over hours**, and the first attempt got that wrong in a way
        worth recording. Walking the day hour by hour carrying "the last building this
        subject was in" is smaller and reads better — and it assumes a subject is in one
        place at a time. A group is not: an odd-week lecture and an even-week lab can share
        an hour, because `group_not_double_booked` compares week patterns and those two never
        meet. The carry then had the group in two buildings at once and counted moves that
        were not there.

        So this is the validator's own shape — sort the day, compare adjacent pairs — with
        "adjacent" as a variable, since which session follows which is what the solver is
        deciding.
        """
        counted: list[cp_model.IntVar] = []
        for _subject, taught in self.people(constraint):
            if len({where for s in taught for where in self.in_building(s)}) < 2:
                # Nowhere to move to. Worth checking rather than modelling: an institution on
                # one site would otherwise pay for this rule in variables and never in cost.
                continue
            for first, second in permutations(taught, 2):
                counted.append(
                    self.all_of(
                        f"move[{first},{second}]",
                        [
                            self._follows(taught, first, second),
                            ~self._same_building(first, second),
                        ],
                    )
                )
        return counted

    def _follows(
        self, taught: Sequence[SessionId], first: SessionId, second: SessionId
    ) -> cp_model.IntVar:
        """True when `second` is the very next thing this subject does, the same day.

        Order is by start hour, ties broken by the order the subject's sessions are indexed
        in — which is what the validator's stable sort on `start_slot` leaves them in.
        Multiplying the start by the number of sessions and adding the position gives one
        number with exactly that ordering, so "before" is a single comparison.

        Nothing has to check that a session in between is on the same day. Days are
        contiguous ranges of hours, so anything starting between two sessions of one day
        starts on that day.
        """
        span = len(taught)
        rank: dict[SessionId, cp_model.LinearExprT] = {
            session_id: span * self.model.starts[session_id] + position
            for position, session_id in enumerate(taught)
        }
        return self.all_of(
            f"next[{first},{second}]",
            [
                self.same_day(first, second),
                self._earlier(rank, first, second),
                *(
                    ~self.all_of(
                        f"between[{first},{second},{other}]",
                        [self._earlier(rank, first, other), self._earlier(rank, other, second)],
                    )
                    for other in taught
                    if other not in (first, second)
                ),
            ],
        )

    def _earlier(
        self,
        rank: Mapping[SessionId, cp_model.LinearExprT],
        first: SessionId,
        second: SessionId,
    ) -> cp_model.IntVar:
        key = (first, "rank", second)
        if key not in self._is:
            flag = self.cp.new_bool_var(f"rank[{first}<{second}]")
            self.cp.add(rank[first] < rank[second]).only_enforce_if(flag)
            self.cp.add(rank[first] > rank[second]).only_enforce_if(~flag)
            self._is[key] = flag
        return self._is[key]

    def _same_building(self, first: SessionId, second: SessionId) -> cp_model.IntVar:
        """True when these two sit in rooms of one building.

        An unassigned building counts as a building: two rooms nobody has placed on a map are
        not two buildings apart, and the validator agrees because it compares `None` with
        `None`.
        """
        key = (first, "building", second)
        if key not in self._is:
            here, there = self.in_building(first), self.in_building(second)
            both = [
                self.all_of(f"both[{first},{second},{where}]", [here[where], there[where]])
                for where in sorted(set(here) & set(there))
            ]
            self._is[key] = self.any_of(
                f"together[{first},{second}]", both or [self.cp.new_constant(0)]
            )
        return self._is[key]

    # -- plumbing ------------------------------------------------------------------

    def any_of(self, name: str, literals: Sequence[cp_model.LiteralT]) -> cp_model.IntVar:
        if len(literals) == 1 and isinstance(literals[0], cp_model.IntVar):
            return literals[0]
        flag = self.cp.new_bool_var(name)
        self.cp.add_max_equality(flag, literals)
        return flag

    def all_of(self, name: str, literals: Sequence[cp_model.LiteralT]) -> cp_model.IntVar:
        flag = self.cp.new_bool_var(name)
        self.cp.add_min_equality(flag, literals)
        return flag

    def _over(self, values: Sequence[int], name: str) -> cp_model.IntVar:
        return self.cp.new_int_var_from_domain(cp_model.Domain.from_values(list(values)), name)

    def _equals(
        self, session_id: SessionId, what: str, var: cp_model.IntVar, value: int
    ) -> cp_model.IntVar:
        """A reified equality, built once per session and value and then shared.

        Two rules asking whether a session is on Tuesday should get the same boolean. Without
        the cache a term with several distribution rules over one set would carry a duplicate
        channelling network per rule, all of them saying the same thing.
        """
        key = (session_id, what, value)
        if key not in self._is:
            flag = self.cp.new_bool_var(f"{what}[{session_id}]={value}")
            self.cp.add(var == value).only_enforce_if(flag)
            self.cp.add(var != value).only_enforce_if(~flag)
            self._is[key] = flag
        return self._is[key]


# -- the rules over named sessions ---------------------------------------------------


def _same_time(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.distinct(constraint, terms.targets(constraint), terms.at_hour)


def _same_room(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.distinct(constraint, terms.targets(constraint), terms.in_room)


def _same_day(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.distinct(constraint, terms.targets(constraint), terms.on_day)


def _different_day(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return [terms.same_day(first, second) for first, second in terms.pairs(constraint)]


def _not_overlap(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """Teaching time, not room occupancy — a turnaround is the room's, not the students'."""
    return [terms.too_close(first, second, 0) for first, second in terms.pairs(constraint)]


def _min_gap(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    wanted = constraint.params["slots"]
    return [terms.too_close(first, second, wanted) for first, second in terms.pairs(constraint)]


def _precedes(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """Each session finishes before the next begins, in session-id order.

    **Ascending id, because the order given is not stored.** `Constraint.targets` is a
    `frozenset`; ITC-2019's `Precedence` keeps the order and Tessera cannot. The validator
    reads it the same way and the backlog carries the gap — what matters here is that both
    read it identically, because a solver optimising one order while the report scores
    another would be the exact drift this phase exists to rule out.
    """
    violated = []
    for earlier, later in pairwise(terms.targets(constraint)):
        in_order = terms.apart(earlier, later, 0)
        flag = terms.cp.new_bool_var(f"disorder[{earlier},{later}]")
        terms.cp.add(flag == 1 - in_order)
        violated.append(flag)
    return violated


def _max_days_between(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """How much wider the spread is than allowed — zero when it is not."""
    targets = terms.targets(constraint)
    if len(targets) < 2:
        return []

    days = [terms.day(session_id) for session_id in targets]
    last = terms.snapshot.grid.days - 1
    latest = terms.cp.new_int_var(0, last, f"latest[{constraint.kind.value}]")
    earliest = terms.cp.new_int_var(0, last, f"earliest[{constraint.kind.value}]")
    terms.cp.add_max_equality(latest, days)
    terms.cp.add_min_equality(earliest, days)

    allowed = constraint.params["days"]
    return [terms.count(constraint, latest - earliest - allowed, last - allowed)]


# -- the preferences over a whole term ------------------------------------------------


def _minimise_group_gaps(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.gaps(constraint, TargetKind.GROUP)


def _minimise_instructor_gaps(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.gaps(constraint, TargetKind.INSTRUCTOR)


def _minimise_building_changes(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.moves(constraint)


def _avoid_same_course_twice_a_day(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """One teaching of a course a day is free; each one after it costs."""
    units = []
    for _course, taught in terms.subjects(constraint, TargetKind.COURSE):
        for day, _ in terms.week():
            today = [terms.on_day(s)[day] for s in taught if day in terms.on_day(s)]
            if len(today) > 1:
                units.append(terms.count(constraint, sum(today) - 1, len(today) - 1))
    return units


def _prefer_room_stability(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """How many rooms a course is spread over, less the one it is entitled to."""
    units = []
    for _course, taught in terms.subjects(constraint, TargetKind.COURSE):
        units.extend(terms.distinct(constraint, taught, terms.in_room))
    return units


def _respect_instructor_preferences(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """The hours somebody said they would rather not teach, at the price they put on them.

    Soft unavailability, which the invariants pass over entirely — *would rather not* is not
    *cannot*, and a solver treating them alike would make every stated preference an
    impossibility.

    Priced off the start variable rather than off a busy-at-this-hour network: what an hour
    costs is known for every hour the session could begin at, so the whole rule is a weighted
    sum over indicators that already exist.
    """
    units = []
    for instructor, taught in terms.subjects(constraint, TargetKind.INSTRUCTOR):
        who = InstructorId(instructor)
        priced: list[tuple[cp_model.IntVar, int]] = []
        for session_id in taught:
            duration = terms.duration(session_id)
            for begin, chosen in terms.at(session_id).items():
                cost = sum(
                    terms.snapshot.preferred_against.get((who, slot), 0)
                    for slot in range(begin, begin + duration)
                )
                if cost:
                    priced.append((chosen, cost))
        if priced:
            units.append(
                terms.count(
                    constraint,
                    cp_model.LinearExpr.weighted_sum(
                        [chosen for chosen, _ in priced], [cost for _, cost in priced]
                    ),
                    sum(cost for _, cost in priced),
                )
            )
    return units


def _balance_daily_load(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """How far the heaviest day rises above a share nobody could avoid.

    Measured against the even share rather than against the lightest day, so it can reach
    zero — #196 found the other reading charging a floor no arrangement could remove, which
    made the weight on this rule move nothing at all. The floor is whichever is larger: an
    even share of the week, or the longest single session, since no day can be lighter than
    something that has to sit somewhere.

    Both of those are **constants**: how much a subject is taught and how long its longest
    session runs do not depend on where anything is put. Only the heaviest day is a variable.
    """
    days = terms.snapshot.grid.days
    units = []
    for subject, taught in terms.people(constraint):
        total = sum(terms.duration(s) for s in taught)
        unavoidable = max(-(-total // days), max(terms.duration(s) for s in taught))

        loads = []
        for day, _ in terms.week():
            load = terms.cp.new_int_var(0, total, f"load[{subject}d{day}]")
            terms.cp.add(
                load
                == sum(
                    terms.duration(s) * terms.on_day(s)[day]
                    for s in taught
                    if day in terms.on_day(s)
                )
            )
            loads.append(load)

        heaviest = terms.cp.new_int_var(0, total, f"heaviest[{subject}]")
        terms.cp.add_max_equality(heaviest, loads)
        units.append(terms.count(constraint, heaviest - unavoidable, total - unavoidable))
    return units


def _limit_consecutive_slots(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    """Hours in a row beyond what somebody will sit through.

    A run of `n` hours costs `n - allowed`, and a run of `n` hours contains exactly
    `n - allowed` stretches of `allowed + 1` consecutive busy hours. So the rule is: count
    the over-long windows. A window straddling a gap or a break contains a free hour and is
    never counted, and windows do not cross days because the validator groups by day first.
    """
    allowed = constraint.params["slots"]
    units = []
    for _subject, taught in terms.people(constraint):
        for _day, slots in terms.week():
            hours = list(slots)
            for first in range(len(hours) - allowed):
                window = [
                    terms.busy_of(taught, slot) for slot in hours[first : first + allowed + 1]
                ]
                # A window with an hour nothing could occupy can never be entirely busy, so
                # it is left out rather than modelled as a constant that is always false.
                busy = [b for b in window if b is not None]
                if len(busy) == len(window):
                    units.append(terms.all_of(f"run[{hours[first]}+{allowed}]", busy))
    return units


#: One builder per kind, and `test_every_kind_is_scored` checks the enum against this rather
#: than trusting it — the same discipline `EVALUATORS` is held to.
TERMS: dict[ConstraintKind, Callable[[Terms, Constraint], list[cp_model.IntVar]]] = {
    ConstraintKind.SAME_TIME: _same_time,
    ConstraintKind.SAME_ROOM: _same_room,
    ConstraintKind.SAME_DAY: _same_day,
    ConstraintKind.DIFFERENT_DAY: _different_day,
    ConstraintKind.NOT_OVERLAP: _not_overlap,
    ConstraintKind.PRECEDES: _precedes,
    ConstraintKind.MIN_GAP: _min_gap,
    ConstraintKind.MAX_DAYS_BETWEEN: _max_days_between,
    ConstraintKind.MINIMISE_GROUP_GAPS: _minimise_group_gaps,
    ConstraintKind.MINIMISE_INSTRUCTOR_GAPS: _minimise_instructor_gaps,
    ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY: _avoid_same_course_twice_a_day,
    ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES: _respect_instructor_preferences,
    ConstraintKind.MINIMISE_BUILDING_CHANGES: _minimise_building_changes,
    ConstraintKind.BALANCE_DAILY_LOAD: _balance_daily_load,
    ConstraintKind.PREFER_ROOM_STABILITY: _prefer_room_stability,
    ConstraintKind.LIMIT_CONSECUTIVE_SLOTS: _limit_consecutive_slots,
}


def enforce(model: Model, snapshot: Snapshot, *, relaxable: bool = False) -> None:
    """The hard rules, and nothing priced. What a feasibility pass needs.

    4.4 finds a timetable before it tries to find a good one, and the model it searches for
    that first answer must not carry the objective: three of the sixteen terms need a boolean
    per subject per hour, which multiplies a department-scale model by nine and stops it
    reaching any solution at all (#225). Leaving the *whole* objective out would be a
    different bug — a hard distribution rule is a constraint, and a first timetable that
    breaks one is not a first timetable — so the hard half is written and the priced half is
    not.

    A term whose rules are all soft, which `default_constraints()` produces, adds nothing here
    and the feasibility model stays exactly the size 4.2 measured.

    `relaxable` writes each hard rule behind an assumption literal of its own, so 4.6 can
    report *which* rule cannot hold rather than only that something cannot. One literal per
    constraint rather than per kind: an institution with three narrowed `MIN_GAP` rules wants
    to be told which of the three, and it is a single row it would edit.
    """
    terms = Terms(model=model, snapshot=snapshot)
    _refuse_what_cannot_be_scored(snapshot)

    for constraint in snapshot.constraints:
        if constraint.is_hard:
            because = (
                model.assume(constraint.kind.value, "constraint", constraint.id)
                if relaxable
                else None
            )
            for unit in TERMS[constraint.kind](terms, constraint):
                obeyed = model.cp.add(unit == 0)
                if because is not None:
                    obeyed.only_enforce_if(because)


def add(model: Model, snapshot: Snapshot) -> Objective | None:
    """Write the term's rules into the model, and return what to minimise.

    `None` when nothing is priced — a term with no soft rules, or one whose rules are all
    hard. There is then no objective at all rather than a constant one, which keeps 4.2's
    measured feasibility times honest: `minimize(0)` turns a satisfaction problem into an
    optimisation problem CP-SAT will go on to prove optimal.

    Hard rules are still written down. They are *refused*, not priced — pinned to zero
    violations — which is what makes D3's "a hard constraint contributes nothing because its
    weight is zero" a true sentence rather than a convenient one.
    """
    terms = Terms(model=model, snapshot=snapshot)
    _refuse_what_cannot_be_scored(snapshot)

    every: list[cp_model.IntVar] = []
    weighted: dict[ConstraintKind, list[tuple[cp_model.IntVar, int]]] = {}

    for constraint in snapshot.constraints:
        units = TERMS[constraint.kind](terms, constraint)
        every.extend(units)
        if constraint.is_hard:
            for unit in units:
                model.cp.add(unit == 0)
        elif constraint.effective_weight:
            weighted.setdefault(constraint.kind, []).extend(
                (unit, constraint.effective_weight) for unit in units
            )

    if not weighted:
        return None

    by_kind: dict[str, cp_model.IntVar] = {}
    for kind, scored in sorted(weighted.items()):
        cost = model.cp.new_int_var(
            0, sum(bounds(unit)[1] * weight for unit, weight in scored), f"cost[{kind.value}]"
        )
        model.cp.add(
            cost
            == cp_model.LinearExpr.weighted_sum(
                [unit for unit, _ in scored], [weight for _, weight in scored]
            )
        )
        by_kind[kind.value] = cost

    total = model.cp.new_int_var(0, sum(bounds(c)[1] for c in by_kind.values()), "penalty")
    model.cp.add(total == sum(by_kind.values()))
    return Objective(total=total, by_kind=by_kind, units=tuple(every))


def _refuse_what_cannot_be_scored(snapshot: Snapshot) -> None:
    """A rule with no term, refused rather than skipped.

    A partial objective is not a smaller version of the right answer — it is a different
    rulebook, silently substituted, and the penalty it reports does not say so.
    """
    unscored = sorted({c.kind for c in snapshot.constraints} - set(TERMS))
    if unscored:
        named = ", ".join(kind.value for kind in unscored)
        raise NotScorableError(f"no objective term exists for: {named}")


def bounds(var: cp_model.IntVar) -> tuple[int, int]:
    """The lowest and highest values a variable may take.

    **The `list` is load-bearing.** A variable's domain is a flattened list of bounds, and
    OR-Tools returns it as a native `repeated_scalar_int64_t` that does not implement
    negative indexing — `domain[-1]` returns `domain[0]` rather than raising. That read the
    ceiling of every boolean as 0, gave every cost variable the domain `[0, 0]`, and so
    turned each soft rule into a hard one: the pinned tests all reported the term infeasible
    while the validator called the same timetable fine. Another API that answers a question
    it did not understand instead of refusing it.

    **Public because the warning has to be reachable.** While this was `_bounds` the trap was
    documented in a place a second module could not reuse, and 4.5's CB-CTT objective promptly
    wrote its own ceiling with `domain[-1]` in it — every cost variable pinned to `[0, 0]`,
    every frozen model infeasible, and the loop reporting a penalty of zero on a timetable the
    checker priced at 2,664. The same trap, in the same repository, twice.
    """
    domain = list(var.proto.domain)
    return int(domain[0]), int(domain[-1])
