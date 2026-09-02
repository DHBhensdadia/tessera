"""ITC-2007 curriculum-based course timetabling, as something Tessera's search can minimise.

**Why this exists rather than a table built from Tessera's own objective.** P5 asks 4.5 to
compare against published best-known results, and there are three ways to produce a number to
set beside 24 for `comp02`. Scoring the mapped term with Tessera's validator gives **0 on all
21** (#229) — the import carries none of CB-CTT's four soft constraints, so the term prices
nothing. Attaching Tessera's default preferences gives a real number for a *different
objective*: reproducible, scientific-looking, and meaningless beside somebody else's. The third
is to compute the published metric, which is this module.

**What it does not do is re-implement the search.** `Competition` is a `CostModel`, so
`solve()` drives it with the same Fix-and-Optimize loop the product ships, freezing and
narrowing and rotating neighbourhoods exactly as it does for a university. That is the whole
point: a benchmark that measured a copy of the loop would be measuring code no user ever runs.

**Three things are true here that are false in `tessera/solver/`:**

* **Capacity is priced, not required** — `Formulation.capacity_is_priced`. Under Tessera's
  rule `comp01` is arithmetically impossible (#213); under CB-CTT's it is a solved instance
  with a penalty. Comparing a stricter problem's results against a looser problem's optima
  would prove nothing.
* **Unavailability is per course**, which Tessera has no way to express — it blocks an
  instructor or a room — so 4.2's mapping carries a course's unavailability only where its
  teacher teaches nothing else and drops the rest. That drop is why every solved instance
  breaks `Availability` when Tessera's own rules are used (#252), so it is written back in
  here, against the instance rather than against the import.
* **The four soft costs are CB-CTT's**, weighted as the formulation weights them: capacity 1
  per standing student, working days 5 per day short, compactness 2 per isolated lecture,
  stability 1 per room beyond the first.

`blame` comes from the **checker**, never from the objective below it — 4.5's D2, which is
4.1's D1 carried across. A search allowed to rank its own neighbourhoods by its own arithmetic
gets to choose the windows that flatter it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from tessera.domain.ids import RoomId
from tessera.domain.validation import Snapshot
from tessera.importers.cbctt import Instance, read
from tessera.importers.cbctt.apply import Mapped, as_solution, mapped
from tessera.importers.cbctt.score import (
    CAPACITY_PENALTY,
    EXTRA_ROOM_PENALTY,
    ISOLATED_LECTURE_PENALTY,
    WORKING_DAY_PENALTY,
    Report,
)
from tessera.importers.cbctt.score import blame as attributed
from tessera.importers.cbctt.score import check as scored
from tessera.importers.cbctt.solution import Placement as Lecture
from tessera.solver.model import Formulation, Model
from tessera.solver.objective import Objective, Terms, bounds

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tessera.domain.ids import SessionId
    from tessera.domain.validation.snapshot import Placement

#: What a benchmark run must be built with. `capacity_is_priced` is the whole difference
#: between Tessera's problem and the competition's, and passing anything else would silently
#: measure the wrong one.
FORMULATION = Formulation(capacity_is_priced=True)


@dataclass(frozen=True)
class Competition:
    """One instance, held both ways: as the file says it, and as Tessera can search it."""

    instance: Instance
    term: Mapped
    snapshot: Snapshot

    @staticmethod
    def read(source: Path | str) -> Competition:
        """Parse an instance and prepare a term with **no Tessera preferences at all**.

        The constraint set is empty on purpose. Every rule that matters here is either
        structural — one lecture per room per period, no curriculum or teacher in two places —
        and therefore already in `model.build`, or it is one of the four this module prices.
        Leaving Tessera's defaults on would optimise a blend of two rulebooks and report the
        result as a CB-CTT score.
        """
        instance = read(Path(source), name=str(source))
        term = mapped(instance)
        return Competition(
            instance=instance,
            term=term,
            snapshot=Snapshot.of(
                grid=term.grid,
                sessions=list(term.sessions),
                rooms=list(term.rooms),
                groups=term.groups,
                unavailability=list(term.unavailability),
                constraints=(),
            ),
        )

    # -- reading a timetable back in the competition's terms ---------------------------

    def lectures(self, placed: Mapping[SessionId, Placement]) -> dict[SessionId, Lecture]:
        """Each session as the lecture it is, keyed by the session it came from.

        `as_solution` walks `sorted(placed)`, so zipping the two is exact — and `strict=True`
        makes a change to that order a failure rather than a silent misattribution.
        """
        written = as_solution(self.term, {s: (p.start_slot, p.room_id) for s, p in placed.items()})
        return dict(zip(sorted(placed), written, strict=True))

    def check(self, placed: Mapping[SessionId, Placement]) -> Report:
        """What the independent checker makes of this timetable."""
        return scored(self.instance, tuple(self.lectures(placed).values()))

    # -- the CostModel protocol ---------------------------------------------------------

    def enforce(self, model: Model) -> None:
        """The one hard rule the model does not already have: per-course unavailability.

        Everything else CB-CTT calls hard is structural and `model.build` has it — every
        lecture placed exactly once, one lecture per room per period, and no curriculum or
        teacher in two places, the last two because a curriculum became a student group and a
        teacher an instructor.

        Written against `self.instance` rather than against the import, because the import
        cannot hold it: Tessera blocks an *instructor*, so 4.2 carries a course's
        unavailability only where its teacher teaches nothing else. Across nineteen solved
        instances that drop is 2,785 rows and 342 violations (#252).
        """
        of_course: dict[str, list[SessionId]] = {}
        for session_id, course_id in self.term.course_of.items():
            of_course.setdefault(course_id, []).append(session_id)

        per_day = self.snapshot.grid.slots_per_day
        for row in self.instance.unavailable:
            slot = row.day * per_day + row.period
            for session_id in of_course.get(row.course, []):
                # No `if session_id in model.starts` guard. `build` gives every session in the
                # term a start, so the only way to miss is a model built from a different term
                # — and a `KeyError` naming the session is a better answer to that than
                # silently leaving the hour open, which is how a benchmark reports a solution
                # the competition would reject.
                model.cp.add(model.starts[session_id] != slot)

    def add(self, model: Model) -> Objective:
        """The four soft costs, weighted as UD2 weights them.

        Hard rules go in first, exactly as `objective.add` does — a round's model is built by
        this method alone, so anything left to `enforce` would be absent from every round and
        present only in the feasibility pass.

        Never `None`: an instance always prices all four, even where a particular timetable
        happens to owe nothing on any of them.
        """
        self.enforce(model)
        terms = Terms(model=model, snapshot=self.snapshot)

        by_kind = {
            "room_capacity": self._capacity(terms),
            "minimum_working_days": self._working_days(terms),
            "curriculum_compactness": self._compactness(terms),
            "room_stability": self._stability(terms),
        }
        total = model.cp.new_int_var(0, sum(bounds(v)[1] for v in by_kind.values()), "penalty")
        model.cp.add(total == sum(by_kind.values()))
        return Objective(total=total, by_kind=by_kind, units=tuple(by_kind.values()))

    def blame(self, placed: Mapping[SessionId, Placement]) -> Mapping[SessionId, int]:
        """What each session costs, as the checker attributes it — never as `add` sees it."""
        cost = attributed(self.instance, tuple(self.lectures(placed).values()))
        return {
            session_id: cost[lecture]
            for session_id, lecture in self.lectures(placed).items()
            if cost.get(lecture)
        }

    # -- the four costs ------------------------------------------------------------------

    def _sessions_of(self, course_id: str) -> list[SessionId]:
        return sorted(s for s, c in self.term.course_of.items() if c == course_id)

    def _capacity(self, terms: Terms) -> cp_model.IntVar:
        """A point per student who would have to stand, per lecture.

        Linear and exact: the overflow of a (lecture, room) pair is known when the model is
        built, so this is a weighted sum over presence literals with no channelling at all.
        """
        weighted: list[tuple[cp_model.IntVar, int]] = []
        for course in self.instance.courses:
            for session_id in self._sessions_of(course.id):
                for room_id, present in terms.in_room(session_id).items():
                    over = course.students - self.snapshot.rooms[RoomId(room_id)].capacity
                    if over > 0:
                        weighted.append((present, over * CAPACITY_PENALTY))
        return _sum_of(terms, "room_capacity", weighted)

    def _working_days(self, terms: Terms) -> cp_model.IntVar:
        """Five points per day a course falls short of the spread it asked for."""
        weighted: list[tuple[cp_model.IntVar, int]] = []
        for course in self.instance.courses:
            sessions = self._sessions_of(course.id)
            if not sessions or course.min_working_days <= 0:
                continue
            used = [
                terms.any_of(
                    f"taught[{course.id},{day}]",
                    [on[day] for s in sessions if day in (on := terms.on_day(s))],
                )
                for day in range(self.snapshot.grid.days)
                if any(day in terms.on_day(s) for s in sessions)
            ]
            short = terms.cp.new_int_var(0, course.min_working_days, f"short[{course.id}]")
            terms.cp.add_max_equality(short, [course.min_working_days - sum(used), 0])
            weighted.append((short, WORKING_DAY_PENALTY))
        return _sum_of(terms, "minimum_working_days", weighted)

    def _compactness(self, terms: Terms) -> cp_model.IntVar:
        """Two points per lecture a curriculum holds with neither neighbouring period busy.

        Per lecture rather than per gap, which is where a paraphrase of this formulation goes
        wrong, and adjacency never crosses a day: the last period of Monday does not neighbour
        the first of Tuesday.
        """
        per_day = self.snapshot.grid.slots_per_day
        weighted: list[tuple[cp_model.IntVar, int]] = []

        for curriculum in self.instance.curricula:
            sessions = sorted(
                s for course_id in curriculum.courses for s in self._sessions_of(course_id)
            )
            if not sessions:
                continue
            busy = {
                slot: found
                for slot in range(self.snapshot.grid.slot_count)
                if (found := terms.busy_of(sessions, slot)) is not None
            }
            for day in range(self.snapshot.grid.days):
                for period in range(per_day):
                    here = busy.get(day * per_day + period)
                    if here is None:
                        continue
                    beside = [
                        busy[day * per_day + period + step]
                        for step in (-1, 1)
                        if 0 <= period + step < per_day and day * per_day + period + step in busy
                    ]
                    alone = terms.all_of(
                        f"alone[{curriculum.id},{day},{period}]", [here, *[~n for n in beside]]
                    )
                    weighted.append((alone, ISOLATED_LECTURE_PENALTY))
        return _sum_of(terms, "curriculum_compactness", weighted)

    def _stability(self, terms: Terms) -> cp_model.IntVar:
        """A point per room a course uses after the first."""
        weighted: list[tuple[cp_model.IntVar, int]] = []
        for course in self.instance.courses:
            sessions = self._sessions_of(course.id)
            if len(sessions) < 2:
                continue
            rooms = sorted({r for s in sessions for r in terms.in_room(s)})
            used = [
                terms.any_of(
                    f"room[{course.id},{room_id}]",
                    [inside[room_id] for s in sessions if room_id in (inside := terms.in_room(s))],
                )
                for room_id in rooms
            ]
            extra = terms.cp.new_int_var(0, max(len(rooms) - 1, 0), f"extra[{course.id}]")
            terms.cp.add_max_equality(extra, [sum(used) - 1, 0])
            weighted.append((extra, EXTRA_ROOM_PENALTY))
        return _sum_of(terms, "room_stability", weighted)


def _sum_of(
    terms: Terms, name: str, weighted: list[tuple[cp_model.IntVar, int]]
) -> cp_model.IntVar:
    """One cost, over a domain that cannot reach below zero.

    The same rule `objective.count` is built on and for the same reason: 0.1's first optimising
    run reported cost 5 with a lower bound of **-7**, because a term that can go negative lets
    CP-SAT improve the objective past the bottom and the bound it then derives is unsound. Here
    every weight is positive and every variable non-negative, so it is impossible by
    construction rather than by care.
    """
    if not weighted:
        return terms.cp.new_int_var(0, 0, f"cost[{name}]")
    ceiling = sum(bounds(var)[1] * weight for var, weight in weighted)
    cost = terms.cp.new_int_var(0, ceiling, f"cost[{name}]")
    terms.cp.add(
        cost
        == cp_model.LinearExpr.weighted_sum(
            [var for var, _ in weighted], [weight for _, weight in weighted]
        )
    )
    return cost
