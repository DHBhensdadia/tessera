"""CB-CTT as a cost model, and whether it says the same thing as the checker.

**The exit condition of 4.5 part 2**, and it is 0.1's discipline one more time: the CP-SAT
objective and the independently written checker must produce the *same integer*, component for
component, on real instances. Two readings that agree are evidence; one reading agreeing with
itself is not.

The toy instance carries the fast tests, so this file is not silent in CI — the ITC-2007
instances live outside the repository and every test that needs them is skipped there. The toy
is small enough to solve to optimality in under a second, which makes it a better home for the
structural assertions anyway.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from tessera.bench import Competition
from tessera.bench.cbctt import FORMULATION
from tessera.domain.ids import SessionId
from tessera.domain.validation import Snapshot
from tessera.domain.validation.snapshot import Placement
from tessera.importers.cbctt.score import Costs
from tessera.importers.cbctt.score import blame as attributed
from tessera.solver import Budget, Formulation, Outcome, Solution, solve
from tessera.solver.model import UnsatisfiableError, build

TOY = Path(__file__).parents[1] / "importers" / "cbctt" / "fixtures" / "toy.ctt"

#: Rounds and work rather than seconds, so the numbers are the same on any machine (#231).
BUDGET = Budget(
    seconds=300,
    deterministic_seconds=10.0,
    rounds=3,
    round_seconds=60,
    round_deterministic_seconds=2.0,
)


def placed(found: Solution) -> dict[SessionId, Placement]:
    return {
        p.session: Placement(
            session_id=p.session, start_slot=p.start_slot, room_id=p.room, is_pinned=False
        )
        for p in found.placements
    }


@pytest.fixture(scope="module")
def toy() -> Competition:
    return Competition.read(TOY)


@pytest.fixture(scope="module")
def solved(toy: Competition) -> Solution:
    return solve(toy.snapshot, BUDGET, FORMULATION, costs=toy)


def first_answer(toy: Competition) -> dict[SessionId, Placement]:
    """Any valid timetable, found without an objective — deliberately a bad one.

    **The solved toy is useless for testing the objective.** It reaches penalty zero, and zero
    is what every term reports whatever weight it carries: mutating the compactness weight from
    two to one, or the working-day weight from five to one, changes nothing anybody can see.
    That is 4.3 part 1's failure — three hundred examples comparing zero with zero — and a
    mutation run is what found it here, with two of eight surviving.

    A feasibility pass has no objective to satisfy, so what it returns costs something on all
    four counts: capacity 30, working days 15, compactness 8, stability 2.
    """
    model = build(toy.snapshot, FORMULATION)
    toy.enforce(model)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    assert solver.solve(model.cp) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return {
        session_id: Placement(
            session_id=session_id,
            start_slot=solver.value(model.starts[session_id]),
            room_id=model.room_of(solver, session_id),
            is_pinned=False,
        )
        for session_id in sorted(model.starts)
    }


def as_the_model_scores_it(toy: Competition, placed: Mapping[SessionId, Placement]) -> Costs:
    """What the CP-SAT objective makes of a timetable, with every session frozen.

    One solution by construction, so this is a read rather than a search — the same trick
    `search._what_it_costs` uses to price an incumbent.
    """
    model = build(toy.snapshot, replace(FORMULATION, hint=False), placed)
    objective = toy.add(model)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    assert solver.solve(model.cp) in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        "the frozen model has no solution, so the timetable and the constraints disagree"
    )
    read = objective.breakdown(solver)
    return Costs(
        room_capacity=read.get("room_capacity", 0),
        minimum_working_days=read.get("minimum_working_days", 0),
        curriculum_compactness=read.get("curriculum_compactness", 0),
        room_stability=read.get("room_stability", 0),
    )


class TestTheTwoReadingsAgreeOnATimetableThatCostsSomething:
    """The fast, CI-visible half of part 2's exit condition, and the one that is not vacuous.

    Every component is non-zero here, so a wrong weight on any of the four shows up. On the
    *solved* toy every component is zero and two of the four weights can be changed freely
    without a single test noticing.
    """

    def test_component_for_component(self, toy: Competition) -> None:
        timetable = first_answer(toy)

        assert as_the_model_scores_it(toy, timetable) == toy.check(timetable).costs

    def test_and_every_component_is_actually_exercised(self, toy: Competition) -> None:
        """The anti-vacuity guard for the guard above. If this term ever stops costing on all
        four, the agreement test starts comparing zero with zero and says so here first."""
        costs = toy.check(first_answer(toy)).costs

        assert costs == Costs(
            room_capacity=30, minimum_working_days=15, curriculum_compactness=8, room_stability=2
        )

    def test_the_total_is_the_sum_of_the_four(self, toy: Competition) -> None:
        timetable = first_answer(toy)

        assert as_the_model_scores_it(toy, timetable).total == toy.check(timetable).penalty == 55


class TestTheObjectiveAndTheCheckerAgree:
    def test_on_the_total(self, toy: Competition, solved: Solution) -> None:
        assert solved.outcome is Outcome.SOLVED
        assert solved.penalty == toy.check(placed(solved)).penalty

    def test_component_for_component(self, toy: Competition, solved: Solution) -> None:
        """A total can agree by accident — two errors of opposite sign in different terms look
        exactly like no error at all, which is why 4.3's exit test decomposes."""
        costs = toy.check(placed(solved)).costs

        assert solved.penalty_breakdown == {
            name: value
            for name, value in sorted(
                (
                    ("room_capacity", costs.room_capacity),
                    ("minimum_working_days", costs.minimum_working_days),
                    ("curriculum_compactness", costs.curriculum_compactness),
                    ("room_stability", costs.room_stability),
                ),
                key=lambda item: -item[1],
            )
            if value
        }

    def test_the_answer_is_a_valid_cbctt_solution(self, toy: Competition, solved: Solution) -> None:
        """The direct answer to #252. Through the mapped path every solved instance broke
        `Availability`, because 4.2 carries a course's unavailability only where its teacher
        teaches nothing else. `Competition.enforce` writes it back from the instance."""
        assert toy.check(placed(solved)).feasible


class TestTheUnavailabilityIsPutBack:
    def test_no_lecture_lands_on_a_blocked_period(self, toy: Competition, solved: Solution) -> None:
        blocked = {(u.course, u.day, u.period) for u in toy.instance.unavailable}
        lectures = toy.lectures(placed(solved)).values()

        assert not {(p.course, p.day, p.period) for p in lectures} & blocked

    def test_it_writes_one_constraint_per_lecture_of_every_blocked_course(
        self, toy: Competition
    ) -> None:
        """The anti-vacuity guard: if `enforce` wrote nothing, the test above would prove only
        that the mapping happened to carry these rows.

        Per **lecture**, not per row: an unavailability names a course, and each of that
        course's lectures is a separate variable that has to be kept off that hour. The toy's
        four teachers each teach one course, so 4.2 does carry all eight of its rows — the
        instances where it cannot are the ones #252 measured at 2,785 dropped.
        """
        lectures_of = {course.id: course.lectures for course in toy.instance.courses}
        expected = sum(lectures_of[row.course] for row in toy.instance.unavailable)

        model = build(toy.snapshot, FORMULATION)
        before = len(model.cp.proto.constraints)
        toy.enforce(model)

        assert expected == 32
        assert len(model.cp.proto.constraints) - before == expected


def crowded(toy: Competition) -> Snapshot:
    """The same term with every room shrunk to one seat: nothing fits anywhere."""
    return Snapshot.of(
        grid=toy.term.grid,
        sessions=list(toy.term.sessions),
        rooms=[room.model_copy(update={"capacity": 1}) for room in toy.term.rooms],
        groups=toy.term.groups,
        unavailability=list(toy.term.unavailability),
        constraints=(),
    )


class TestTheCapacityRelaxationDoesNotLeak:
    def test_the_product_still_refuses_a_room_that_is_too_small(self, toy: Competition) -> None:
        """Tessera's rule is unchanged: a room that seats sixty seats sixty (#213). With every
        room down to one seat the default formulation refuses to build at all — the same
        refusal that makes `comp01` impossible."""
        with pytest.raises(UnsatisfiableError, match="no room that can hold it"):
            build(crowded(toy), Formulation())

    def test_the_benchmark_prices_it_instead(self, toy: Competition) -> None:
        """The same term, the same rooms, and a model rather than a refusal."""
        model = build(crowded(toy), FORMULATION)

        assert len(model.candidates) == len(toy.term.sessions)
        assert all(model.candidates.values()), "every session needs a room it may be priced in"

    def test_the_default_formulation_requires_capacity(self) -> None:
        """A guard against the flag drifting on. Nothing in `tessera/` may set it, which
        `import-linter` enforces by making `tessera.bench` a leaf."""
        assert Formulation().capacity_is_priced is False
        assert FORMULATION.capacity_is_priced is True


class TestBlameComesFromTheChecker:
    def test_it_is_the_checkers_attribution_and_not_the_objectives(
        self, toy: Competition, solved: Solution
    ) -> None:
        """4.5's D2, which is 4.1's D1 carried across: a search that ranks its own
        neighbourhoods by its own arithmetic gets to choose the windows that flatter it."""
        timetable = placed(solved)
        lectures = toy.lectures(timetable)
        expected = attributed(toy.instance, tuple(lectures.values()))

        assert toy.blame(timetable) == {
            session: expected[lecture]
            for session, lecture in lectures.items()
            if expected.get(lecture)
        }

    def test_a_costly_timetable_blames_the_sessions_that_cost(self, toy: Competition) -> None:
        """Everything into one room on one day: capacity, working days and stability all bite,
        and every session should be named."""
        one_room = min(toy.snapshot.rooms)
        heaped = {
            session_id: Placement(
                session_id=session_id, start_slot=n, room_id=one_room, is_pinned=False
            )
            for n, session_id in enumerate(sorted(toy.snapshot.sessions))
        }
        blamed = toy.blame(heaped)

        assert blamed, "a plainly bad timetable blamed nobody"
        assert set(blamed) <= set(toy.snapshot.sessions)


class TestTheLoopIsTheOneThatShips:
    def test_it_stopped_because_it_had_finished(self, solved: Solution) -> None:
        """The toy is small enough for the unrestricted attempt to prove optimality outright,
        and a penalty of zero ends the loop (#241) — so one step, not three. That is the
        shipped loop's own stopping rule applying to a problem statement it has never seen."""
        assert solved.penalty == 0
        assert solved.bound_is_proven
        assert [step.strategy for step in solved.trajectory] == ["whole"]

    def test_nothing_in_the_descent_ever_rose(self, solved: Solution) -> None:
        assert [step.penalty for step in solved.trajectory] == sorted(
            (step.penalty for step in solved.trajectory), reverse=True
        )

    def test_the_strategies_are_the_shipped_ones(self, solved: Solution) -> None:
        from tessera.solver.neighbourhood import STRATEGIES

        assert {step.strategy for step in solved.trajectory} <= {"whole", *STRATEGIES}


def instances() -> Path | None:
    given = os.environ.get("TESSERA_ITC2007_INSTANCES")
    if not given:
        return None
    found = Path(given).expanduser()
    return found if list(found.glob("comp*.ctt")) else None


ROOT = instances()


@pytest.mark.benchmark
@pytest.mark.skipif(ROOT is None, reason="set TESSERA_ITC2007_INSTANCES")
@pytest.mark.parametrize("name", ["comp01", "comp05", "comp11"])
def test_the_two_readings_agree_on_a_real_instance(name: str) -> None:
    """The toy has four courses. `comp05` has 152 lectures and nine curricula per course, and
    an objective that is right on a toy and wrong at scale is the usual way this fails."""
    assert ROOT is not None
    instance = Competition.read(ROOT / f"{name}.ctt")
    found = solve(instance.snapshot, BUDGET, FORMULATION, costs=instance)
    report = instance.check(placed(found))

    assert found.outcome is Outcome.SOLVED
    assert found.penalty == report.penalty
    assert report.feasible, report.violations


@pytest.mark.benchmark
@pytest.mark.skipif(ROOT is None, reason="set TESSERA_ITC2007_INSTANCES")
def test_comp01_is_solvable_under_the_competitions_rules_and_not_under_tesseras() -> None:
    """#213, from both sides at once, and the clearest statement of why D1 chose route A.

    `comp01` has 64 lectures needing a room for 31 and a week containing 60 such room-periods.
    Under Tessera's hard capacity that is arithmetic and no solver can help; under CB-CTT's,
    where a standing student costs a point, it is an ordinary instance.
    """
    assert ROOT is not None
    instance = Competition.read(ROOT / "comp01.ctt")

    found = solve(instance.snapshot, BUDGET, FORMULATION, costs=instance)
    assert found.outcome is Outcome.SOLVED
    assert instance.check(placed(found)).feasible

    strictly = solve(instance.snapshot, Budget(seconds=60, deterministic_seconds=20.0, rounds=0))
    assert strictly.outcome is not Outcome.SOLVED


SPARSE = """Name: Sparse
Courses: 3
Rooms: 2
Days: 2
Periods_per_day: 2
Curricula: 2
Constraints: 0

COURSES:
Solo Ann 1 0 5
Duo Bob 2 1 5
Never Cid 0 0 5

ROOMS:
Big 100
Small 90

CURRICULA:
Cur1 1 Solo
Cur2 1 Never

UNAVAILABILITY_CONSTRAINTS:

END.
"""


class TestTheEdgesOfTheFormulation:
    """Instances where a cost has nothing to say.

    Each of these is a real shape a `.ctt` file may take, and each takes a different branch out
    of the four cost builders. They are here because the branches exist, and a branch nothing
    reaches is a branch nobody has checked — an objective that raised on a course with a single
    lecture would be found by an institution rather than by this.
    """

    @pytest.fixture
    def sparse(self, tmp_path: Path) -> Competition:
        instance = tmp_path / "sparse.ctt"
        instance.write_text(SPARSE)
        return Competition.read(instance)

    def test_a_course_with_one_lecture_cannot_be_unstable(self, sparse: Competition) -> None:
        """Stability is rooms *beyond the first*, so a single lecture is always in exactly one
        room and the term is skipped rather than built as a constant."""
        found = solve(sparse.snapshot, BUDGET, FORMULATION, costs=sparse)

        assert found.outcome is Outcome.SOLVED
        assert sparse.check(placed(found)).costs.room_stability == 0

    def test_a_course_asking_for_no_working_days_is_never_short(self, sparse: Competition) -> None:
        found = solve(sparse.snapshot, BUDGET, FORMULATION, costs=sparse)

        assert sparse.check(placed(found)).costs.minimum_working_days == 0

    def test_rooms_nobody_can_fill_cost_nothing(self, sparse: Competition) -> None:
        """Every room is far larger than every class, so the capacity term has no lecture to
        price at all — the case where the weighted sum is empty rather than zero.

        The instance is not free, and that is the useful part: `Solo` is the whole of `Cur1`
        and a curriculum with one lecture has an isolated one, so two points remain. An empty
        capacity term has to leave the other three alone.
        """
        found = solve(sparse.snapshot, BUDGET, FORMULATION, costs=sparse)
        costs = sparse.check(placed(found)).costs

        assert costs.room_capacity == 0
        assert costs.curriculum_compactness == 2
        assert found.penalty == costs.total == 2

    def test_a_curriculum_whose_courses_are_never_taught(self, sparse: Competition) -> None:
        """`Never` declares zero lectures, so `Cur2` has no sessions and compactness has
        nothing to count for it. The instance is still legible and still solves."""
        assert sparse.term.course_of and "Never" not in set(sparse.term.course_of.values())

        found = solve(sparse.snapshot, BUDGET, FORMULATION, costs=sparse)

        assert found.outcome is Outcome.SOLVED
        assert sparse.check(placed(found)).feasible
