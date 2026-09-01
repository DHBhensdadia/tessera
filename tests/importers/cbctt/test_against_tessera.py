"""The checker read against real instances, by a solver that has never heard of it.

**The gap this closes is not "can it fail" — `test_score.py` covers that, in both directions.**
A first draft of this docstring claimed the toy suite would pass a checker that condemned every
lecture; that was checked rather than asserted, and it is wrong. Making room occupancy fire on
every used room-period fails **fourteen** of the toy tests, because the hand-built solution
scoring zero is itself a false-positive detector.

What the toy suite cannot do is be independent. That fixture and this checker were written by
one person from one reading of the specification, within an hour of each other. A misreading
would appear in both — the timetable built to be "known-good" would be built to satisfy the
same wrong rule the checker enforces, and every test would pass.

Tessera's solver is the second reading. It was written for 4.2, from Tessera's own domain,
months before any of this existed, and it enforces three of CB-CTT's four hard rules because
they are also Tessera's. Running it on the instances and scoring what it produces asks whether
two independent implementations agree over **5,401 lectures** — `comp02` alone is 283 — which
is the kind of agreement Phase 0.1 got across 21 instances and called evidence.

**And they nearly agree, in a way that is exactly informative.** Tessera's rules are a superset
of CB-CTT's three structural ones, and *stricter* on room capacity, so a Tessera timetable can
never break `Lectures`, `Conflicts` or `RoomOccupancy` and can never pay a capacity penalty.
The one place it can differ is `Availability`, and only there, because 4.2's mapping carries a
course's unavailability **only where its teacher teaches nothing else** — blocking the teacher
otherwise would forbid hours the instance never forbade. Tessera is not told about the rest, so
it schedules into them freely.

That makes the interesting assertion sharp: every violation this checker reports must land on
an unavailability the mapping is *known* to have dropped, and none on one it carried. A checker
reading day and period the wrong way round, or off by one, would put violations on carried
constraints and fail — which is a check on real data that no toy instance can give.

Marked `benchmark`: it needs the instances, and it solves.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tessera.domain.validation import Snapshot
from tessera.importers.cbctt import read
from tessera.importers.cbctt.apply import as_solution, mapped
from tessera.importers.cbctt.format import Instance
from tessera.importers.cbctt.score import Report, check
from tessera.importers.cbctt.solution import Placement
from tessera.solver import Budget, Outcome, solve

pytestmark = pytest.mark.benchmark

#: Chosen for breadth and for running in about half a minute rather than ten — the full
#: 21-instance sweep is in the phase record, where a number that takes minutes belongs.
#: `comp18` is here deliberately: every one of its unavailability rows is carried, so it is the
#: positive control. If the availability check were simply always firing, comp18 would say so.
INSTANCES = ("comp02", "comp03", "comp05", "comp11", "comp12", "comp18")

BUDGET = Budget(seconds=120, deterministic_seconds=40.0, rounds=0)


def directory() -> Path | None:
    given = os.environ.get("TESSERA_ITC2007_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if list(found.glob("comp*.ctt")) else None


ROOT = directory()
needs_download = pytest.mark.skipif(
    ROOT is None, reason="set TESSERA_ITC2007_INSTANCES to the ITC-2007 directory"
)


class Solved:
    """One instance, solved once, so six assertions do not cost six solves."""

    def __init__(self, instance: Instance, placements: tuple[Placement, ...]) -> None:
        self.instance = instance
        self.placements = placements
        self.report: Report = check(instance, placements)

    @property
    def dropped(self) -> set[tuple[str, int, int]]:
        """The unavailability 4.2 could not carry, recomputed from its stated rule.

        Recomputed rather than read off the ledger because the ledger counts them and does not
        name them, and the assertions here are about *which*. The rule is one line and it is
        the mapping's own: carried where the teacher teaches a single course.
        """
        teaches: dict[str, list[str]] = {}
        for course in self.instance.courses:
            teaches.setdefault(course.teacher, []).append(course.id)
        return {
            (u.course, u.day, u.period)
            for u in self.instance.unavailable
            if len(teaches[self.instance.teacher_of(u.course)]) > 1
        }

    @property
    def carried(self) -> set[tuple[str, int, int]]:
        every = {(u.course, u.day, u.period) for u in self.instance.unavailable}
        return every - self.dropped

    @property
    def occupied(self) -> set[tuple[str, int, int]]:
        return {(p.course, p.day, p.period) for p in self.placements}


@pytest.fixture(scope="module", params=INSTANCES)
def solved(request: pytest.FixtureRequest) -> Solved:
    assert ROOT is not None
    instance = read(ROOT / f"{request.param}.ctt")
    term = mapped(instance)
    found = solve(
        Snapshot.of(
            grid=term.grid,
            sessions=list(term.sessions),
            rooms=list(term.rooms),
            groups=term.groups,
            unavailability=list(term.unavailability),
            constraints=(),
        ),
        BUDGET,
    )
    if found.outcome is not Outcome.SOLVED:
        pytest.fail(f"{request.param} did not solve — {found.outcome.value}")
    return Solved(
        instance,
        as_solution(term, {p.session: (p.start_slot, p.room) for p in found.placements}),
    )


@needs_download
class TestWhatTwoIndependentReadingsAgreeOn:
    def test_every_lecture_is_placed_exactly_once(self, solved: Solved) -> None:
        assert len(solved.placements) == solved.instance.lectures

    def test_nothing_structural_is_ever_broken(self, solved: Solved) -> None:
        """`Lectures`, `Conflicts` and `RoomOccupancy` are rules Tessera enforces too, from a
        model written before this checker existed. Any of them firing here is a disagreement
        between two independent readings, and one of them would be wrong."""
        assert solved.report.rules_broken <= {"Availability"}, solved.report.violations

    def test_no_student_ever_has_to_stand(self, solved: Solved) -> None:
        """Room capacity is a hard invariant in Tessera and a priced one in CB-CTT (#213), so
        the cost that CB-CTT would charge is always zero here. It is the one soft cost this
        cross-check can pin, and pinning it needs the solver rather than a fixture."""
        assert solved.report.costs.room_capacity == 0


@needs_download
class TestWhereTheyDisagreeIsWhereTheMappingSaidItWould:
    def test_every_violation_lands_on_an_unavailability_that_was_dropped(
        self, solved: Solved
    ) -> None:
        """The sharp one. A checker off by one on the day, or reading the period as the day,
        would put violations on constraints the solver *was* given and did respect."""
        broken = solved.occupied & (solved.dropped | solved.carried)

        assert broken <= solved.dropped
        assert len(solved.report.violations) == len(broken)

    def test_nothing_the_solver_was_told_about_is_violated(self, solved: Solved) -> None:
        """The same claim from the other side, and the one that would catch a checker reading
        the *file* correctly while the mapping read it wrongly."""
        assert not solved.occupied & solved.carried


@needs_download
def test_the_positive_control_is_a_valid_cbctt_solution() -> None:
    """`comp18` is the instance where every teacher teaches one course, so nothing is dropped
    and Tessera is given the whole problem. Its timetable is a **valid CB-CTT solution** —
    which is what says the availability check is capable of not firing."""
    assert ROOT is not None
    instance = read(ROOT / "comp18.ctt")
    term = mapped(instance)
    found = solve(
        Snapshot.of(
            grid=term.grid,
            sessions=list(term.sessions),
            rooms=list(term.rooms),
            groups=term.groups,
            unavailability=list(term.unavailability),
            constraints=(),
        ),
        BUDGET,
    )
    solution = as_solution(term, {p.session: (p.start_slot, p.room) for p in found.placements})
    report = check(instance, solution)

    assert report.feasible, report.violations
