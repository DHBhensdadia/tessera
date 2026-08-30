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

**Weights come from the constraints, never from constants.** 2.8 put a weight on `Constraint`
and 3.5 put sliders on the rules screen; an objective with numbers baked in would make those
sliders decorative, which is the worst kind of interface defect because it looks like it
works. A *hard* constraint has `effective_weight` 0 and is not priced at all — it is pinned to
zero units, refused rather than traded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, pairwise
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from tessera.domain.constraints import Constraint, ConstraintKind
from tessera.domain.ids import SessionId
from tessera.domain.validation import Snapshot
from tessera.solver.model import Model

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence


#: The kinds part 2 adds. Present so that ignoring one is impossible rather than merely
#: unlikely: `add` raises on a kind it cannot score, and part 2 empties this set.
#:
#: Silence is the failure D4 is about. An institution sets "minimise gaps", a partial
#: objective omits the term, the solver optimises everything else, and the number reported is
#: confidently wrong — nothing in the output says a rule was skipped.
PENDING: frozenset[ConstraintKind] = frozenset(
    {
        ConstraintKind.MINIMISE_GROUP_GAPS,
        ConstraintKind.MINIMISE_INSTRUCTOR_GAPS,
        ConstraintKind.AVOID_SAME_COURSE_TWICE_A_DAY,
        ConstraintKind.RESPECT_INSTRUCTOR_PREFERENCES,
        ConstraintKind.MINIMISE_BUILDING_CHANGES,
        ConstraintKind.BALANCE_DAILY_LOAD,
        ConstraintKind.PREFER_ROOM_STABILITY,
        ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
    }
)


class NotScorableError(NotImplementedError):
    """A rule this part cannot express, met in a term it was asked to solve.

    Loud on purpose. The quiet alternative — score the kinds we have and omit the rest —
    produces a timetable optimised against a rulebook nobody wrote down, and a penalty that
    does not answer for the difference.
    """


@dataclass(frozen=True)
class Objective:
    """What the model minimises, and how to read the result back out.

    `by_kind` is per `ConstraintKind` rather than per constraint, matching
    `Report.penalty_breakdown`: an institution with three narrowed `MIN_GAP` rules wants to
    know what gaps cost it, not what rule 14 cost it. Reporting them the same way is what
    makes the two comparable at all.
    """

    total: cp_model.IntVar
    by_kind: dict[ConstraintKind, cp_model.IntVar]

    units: tuple[cp_model.IntVar, ...] = ()
    """Every violation count the terms produced, hard ones included.

    Kept so a test can walk them and assert what D2 claims: not one has a domain that
    reaches below zero. A guarantee nobody checks is a comment."""

    def floors(self) -> tuple[int, ...]:
        """The lowest value each violation count may take. Every one of them is zero."""
        return tuple(_bounds(unit)[0] for unit in self.units)

    def penalty(self, solver: cp_model.CpSolver) -> int:
        return int(solver.value(self.total))

    def breakdown(self, solver: cp_model.CpSolver) -> dict[str, int]:
        """The penalty by rule, largest first — `Report.penalty_breakdown`'s shape exactly.

        Zero-cost kinds are dropped for the same reason the validator drops them: a rule an
        institution set and never broke is not a line in a report about what went wrong.
        """
        scored = {kind.value: int(solver.value(var)) for kind, var in self.by_kind.items()}
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
        choices: Callable[[SessionId], Mapping[int, cp_model.IntVar]],
    ) -> list[cp_model.IntVar]:
        """How many different values these sessions take, less one. `rules._agree_on`.

        Reported as one count for the whole set rather than one per session that differs,
        which is what the validator does and for the reason it gives: a person told four
        times that four sessions disagree has been told one thing.

        Fewer than two sessions is silence on both sides — one session cannot disagree with
        itself, and the validator's `len(placed) > 1` says so.
        """
        targets = self.targets(constraint)
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

    # -- plumbing ------------------------------------------------------------------

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
    return terms.distinct(constraint, terms.at_hour)


def _same_room(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.distinct(constraint, terms.in_room)


def _same_day(terms: Terms, constraint: Constraint) -> list[cp_model.IntVar]:
    return terms.distinct(constraint, terms.on_day)


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


#: One builder per kind, and `test_every_kind_is_scored_or_named_as_pending` checks the enum
#: against this rather than trusting it — the same discipline `EVALUATORS` is held to.
TERMS: dict[ConstraintKind, Callable[[Terms, Constraint], list[cp_model.IntVar]]] = {
    ConstraintKind.SAME_TIME: _same_time,
    ConstraintKind.SAME_ROOM: _same_room,
    ConstraintKind.SAME_DAY: _same_day,
    ConstraintKind.DIFFERENT_DAY: _different_day,
    ConstraintKind.NOT_OVERLAP: _not_overlap,
    ConstraintKind.PRECEDES: _precedes,
    ConstraintKind.MIN_GAP: _min_gap,
    ConstraintKind.MAX_DAYS_BETWEEN: _max_days_between,
}


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

    by_kind: dict[ConstraintKind, cp_model.IntVar] = {}
    for kind, scored in sorted(weighted.items()):
        cost = model.cp.new_int_var(
            0, sum(_bounds(unit)[1] * weight for unit, weight in scored), f"cost[{kind.value}]"
        )
        model.cp.add(
            cost
            == cp_model.LinearExpr.weighted_sum(
                [unit for unit, _ in scored], [weight for _, weight in scored]
            )
        )
        by_kind[kind] = cost

    total = model.cp.new_int_var(0, sum(_bounds(c)[1] for c in by_kind.values()), "penalty")
    model.cp.add(total == sum(by_kind.values()))
    return Objective(total=total, by_kind=by_kind, units=tuple(every))


def _refuse_what_cannot_be_scored(snapshot: Snapshot) -> None:
    """Part 2's kinds, met before part 2 exists.

    Raising rather than skipping. A partial objective is not a smaller version of the right
    answer — it is a different rulebook, silently substituted, and the penalty it reports
    does not say so.
    """
    unscored = sorted({c.kind for c in snapshot.constraints} - set(TERMS))
    if not unscored:
        return
    named = ", ".join(kind.value for kind in unscored)
    if set(unscored) <= PENDING:
        raise NotScorableError(f"4.3 part 2 adds the objective term(s) for: {named}")
    raise NotScorableError(f"no objective term exists for: {named}")  # pragma: no cover


def _bounds(var: cp_model.IntVar) -> tuple[int, int]:
    """The lowest and highest values a variable may take.

    **The `list` is load-bearing.** A variable's domain is a flattened list of bounds, and
    OR-Tools returns it as a native `repeated_scalar_int64_t` that does not implement
    negative indexing — `domain[-1]` returns `domain[0]` rather than raising. That read the
    ceiling of every boolean as 0, gave every cost variable the domain `[0, 0]`, and so
    turned each soft rule into a hard one: the pinned tests all reported the term infeasible
    while the validator called the same timetable fine. Another API that answers a question
    it did not understand instead of refusing it.
    """
    domain = list(var.proto.domain)
    return int(domain[0]), int(domain[-1])
