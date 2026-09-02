"""P5's untested headroom, tested before the outer search is written.

> **Before assuming LNS must do all the work**, try the untested headroom in the naive model:
> symmetry breaking between identical rooms, search hints, redundant constraints.

The measured effect of each is in the phase record, because a number in a test is a number
nobody reads. What is asserted here is the half that a measurement cannot show: that none of
the three changes **which timetables are legal**.

That matters most for the symmetry break. An over-strong one removes valid answers, and the
symptom is a slightly worse optimum on some instances — a change nobody would attribute to the
room grouping, arriving in a phase whose whole subject is scores getting better. #207 is the
precedent: a room-grouping change that looked obviously better and was five times worse, found
only because it was measured rather than reasoned about.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from ortools.sat.python import cp_model

from tessera.domain.entities import Room, Session, SessionKind, Unavailability
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.ids import (
    AssignmentId,
    BuildingId,
    InstructorId,
    RoomId,
    SessionId,
    StudentGroupId,
)
from tessera.domain.time_grid import TimeGrid
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Outcome, Solution, solve
from tessera.solver.model import Formulation, UnsatisfiableError, _alike, build
from tessera.solver.objective import TERMS
from tests.domain.validation.generated import Instance
from tests.solver.generated import snapshot_of, to_score
from tests.solver.scored import cbctt, department, with_timetable

#: Every lever off, stated rather than defaulted. `Formulation()` is no longer this — the
#: measurement turned the hint on — and a baseline that quietly acquires a lever is how a
#: comparison stops comparing what it says it does.
PLAIN = Formulation(symmetry=False, redundant=False, hint=False)

#: The levers that change the *model*. The hint changes only where the search starts, so it
#: cannot remove a timetable and is checked separately.
LEVERS = st.sampled_from(
    [
        Formulation(symmetry=True, hint=False),
        Formulation(redundant=True, hint=False),
        Formulation(symmetry=True, redundant=True, hint=False),
    ]
)

CAREFUL = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

#: One short day. Small enough to enumerate every timetable there is, which is what the
#: symmetry break has to be checked against rather than argued about.
DAY = TimeGrid(days=1, slots_per_day=4, slot_minutes=60, day_start_minute=9 * 60)

COHORT = StudentGroupId(1)


def rooms(count: int) -> list[Room]:
    """Rooms with nothing to tell them apart."""
    return [Room(id=RoomId(i), name=f"Room {i}", capacity=30) for i in range(1, count + 1)]


def term(
    estate: list[Room],
    sessions: int = 2,
    *,
    unavailability: tuple[Unavailability, ...] = (),
    assignments: tuple[Assignment, ...] = (),
) -> Snapshot:
    """A term with one cohort, so its sessions cannot share an hour."""
    return Snapshot.of(
        grid=DAY,
        sessions=[
            Session(
                id=SessionId(i),
                kind=SessionKind.LECTURE,
                duration_slots=1,
                attendee_ids=frozenset({COHORT}),
                instructor_ids=frozenset({InstructorId(1)}),
            )
            for i in range(1, sessions + 1)
        ],
        rooms=estate,
        groups=GroupSet(
            [StudentGroup(id=COHORT, name="Cohort", size=20, kind=GroupKind.STRUCTURAL)]
        ),
        unavailability=unavailability,
        assignments=assignments,
    )


def classes(snapshot: Snapshot) -> list[list[RoomId]]:
    return _alike(build(snapshot), snapshot)


def timetables(snapshot: Snapshot, formulation: Formulation) -> int:
    """Every timetable this model admits, counted.

    The only way to show a symmetry break *removes* something is to count what is left. An
    auxiliary variable cannot inflate the count: rank and running-maximum are both determined
    by the placement, so two enumerated solutions still differ in a placement.
    """

    class Counter(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.found = 0

        def on_solution_callback(self) -> None:
            self.found += 1

    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.num_workers = 1
    counter = Counter()
    solver.solve(build(snapshot, formulation).cp, counter)
    return counter.found


class TestWhichRoomsAreActuallyAlike:
    """Interchangeability is not "same capacity", and every difference here was a way to
    remove a valid timetable by treating two rooms as one."""

    def test_rooms_with_nothing_to_tell_them_apart_are_one_class(self) -> None:
        assert classes(term(rooms(4))) == [[RoomId(1), RoomId(2), RoomId(3), RoomId(4)]]

    def test_a_closure_makes_a_room_its_own(self) -> None:
        """`room_closed` is per `(room, slot)`. A room shut on Tuesday morning is not the
        room next door, and swapping the two would move a class into a closed room."""
        estate = rooms(3)
        shut = term(estate, unavailability=(Unavailability(room_id=RoomId(2), slot=0),))

        assert classes(shut) == [[RoomId(1), RoomId(3)]]

    def test_a_different_building_makes_a_room_its_own(self) -> None:
        """`MINIMISE_BUILDING_CHANGES` reads `building_id`, so two rooms in different
        buildings score differently and are not substitutes."""
        estate = rooms(3)
        estate[1] = estate[1].model_copy(update={"building_id": BuildingId(9)})

        assert classes(term(estate)) == [[RoomId(1), RoomId(3)]]

    def test_a_different_turnaround_makes_a_room_its_own(self) -> None:
        """The turnaround is in the interval's length, so the two rooms hold a session for
        different amounts of time."""
        estate = rooms(3)
        estate[1] = estate[1].model_copy(update={"turnaround_slots": 1})

        assert classes(term(estate)) == [[RoomId(1), RoomId(3)]]

    def test_a_different_capacity_makes_a_room_its_own(self) -> None:
        estate = rooms(3)
        estate[1] = estate[1].model_copy(update={"capacity": 500})

        assert classes(term(estate)) == [[RoomId(1), RoomId(3)]]

    def test_a_room_somebody_pinned_is_nobody_s_twin(self) -> None:
        """The one that would have been a bug rather than an inefficiency.

        A pin names a room, so the rooms of a class stop being substitutable the moment one is
        fixed: precedence would then require the earlier rooms to be in use before the pinned
        one may be, and refuse a timetable that is perfectly legal.
        """
        pinned = term(
            rooms(3),
            assignments=(
                Assignment(
                    id=AssignmentId(1),
                    session_id=SessionId(1),
                    start_slot=0,
                    room_id=RoomId(3),
                    is_pinned=True,
                ),
            ),
        )

        assert classes(pinned) == [[RoomId(1), RoomId(2)]]


class TestFillingAlikeRoomsInOrder:
    def test_it_removes_timetables_that_are_only_relabellings(self) -> None:
        """The anti-vacuity guard. A symmetry break that removed nothing would pass every
        safety test in this file by doing nothing at all."""
        two_in_three = term(rooms(3), sessions=2)

        assert timetables(two_in_three, Formulation(symmetry=True, hint=False)) < timetables(
            two_in_three, PLAIN
        )

    def test_it_never_removes_the_last_one(self) -> None:
        """Fewer, but never none: a term with a timetable still has one afterwards."""
        packed = term(rooms(2), sessions=2)

        assert timetables(packed, Formulation(symmetry=True, hint=False)) > 0

    def test_a_pinned_session_still_solves(self) -> None:
        """What `test_a_room_somebody_pinned_is_nobody_s_twin` protects, end to end. Pin a
        session into the last of three identical rooms — precedence would call that
        impossible."""
        pinned = term(
            rooms(3),
            sessions=2,
            assignments=(
                Assignment(
                    id=AssignmentId(1),
                    session_id=SessionId(1),
                    start_slot=0,
                    room_id=RoomId(3),
                    is_pinned=True,
                ),
            ),
        )
        found = solve(pinned, Budget(seconds=10), Formulation(symmetry=True, hint=False))

        assert found.solved
        assert [p.room for p in found.placements if p.session == SessionId(1)] == [RoomId(3)]


class TestNoMoreAtOnceThanThereAreRooms:
    def test_it_is_only_stated_where_it_could_bite(self) -> None:
        """With more rooms than sessions the count is true before the search starts, and a
        constraint that cannot fail is a constraint the presolve has to read anyway."""
        roomy = term(rooms(6), sessions=2)

        assert len(
            build(roomy, Formulation(redundant=True, hint=False)).cp.proto.constraints
        ) == len(build(roomy, PLAIN).cp.proto.constraints)

    def test_it_is_stated_where_it_can(self) -> None:
        crowded = term(rooms(2), sessions=6)

        assert len(
            build(crowded, Formulation(redundant=True, hint=False)).cp.proto.constraints
        ) > len(build(crowded, PLAIN).cp.proto.constraints)


#: Terms where the symmetry break is at full strength *and* the answer is not zero. Both
#: halves are asserted rather than hoped for, because the generated terms turned out to
#: supply neither: of 90 drawn from `to_score`, **12** contained two rooms this model cannot
#: tell apart, and **none of those 12** scored anything at its optimum. A property run over
#: them would have compared zero with zero on the eighth of examples that reached the code at
#: all — which is what 4.3 part 1 shipped for a day, and the reason this is a table.
SHAPED: list[tuple[str, int, int, int]] = [
    ("dept(24,6)", 24, 6, 1),
    ("dept(24,6) on two sites", 24, 6, 2),
]

#: Enough work to *prove* an optimum on these shapes, and budgeted in work so that whether it
#: is proven stops being a fact about the machine. They need 3.2 to 4.5 units; this is twenty.
#:
#: It used to be `Budget(seconds=30)`, and the test failed once on a laptop six hours into
#: continuous CP-SAT: the unrestricted attempt did not finish, the loop spun to round 93, and
#: `is_optimal` was false for a reason with nothing to do with the levers (#264). Whether two
#: formulations reach the *same* optimum is what this is about, and that is a fact about the
#: model. `rounds=0` keeps it about the unrestricted attempt, which is the only thing that can
#: prove one, and makes a failure quick rather than a five-minute spin.
PROVEN = Budget(seconds=300, deterministic_seconds=20.0, rounds=0)


@pytest.fixture(scope="module")
def unlevered() -> dict[str, object]:
    """The plain answer per shape, solved once. Six parametrisations would otherwise re-derive
    the same two baselines four times each, and a baseline is the one thing in a comparison
    that cannot differ between rows."""
    return {}


class TestNoLeverChangesTheAnswer:
    @pytest.mark.parametrize(
        ("name", "sessions", "rooms", "buildings"), SHAPED, ids=[shape[0] for shape in SHAPED]
    )
    @pytest.mark.parametrize(
        "lever",
        [
            Formulation(symmetry=True, hint=False),
            Formulation(redundant=True, hint=False),
            Formulation(symmetry=True, redundant=True, hint=False),
        ],
        ids=["symmetry", "redundant", "both"],
    )
    def test_the_optimum_survives_every_lever(
        self,
        name: str,
        sessions: int,
        rooms: int,
        buildings: int,
        lever: Formulation,
        unlevered: dict[str, object],
    ) -> None:
        """The claim that matters, on terms measured to be able to show it failing.

        A weaker model would show up here as a *higher* optimum — the timetable that scored
        best is no longer reachable — and on a term whose optimum is zero there is no room
        below to lose.
        """
        snapshot = department(sessions, rooms, buildings=buildings)

        assert _alike(build(snapshot), snapshot), f"{name} has no interchangeable rooms"
        if name not in unlevered:
            unlevered[name] = solve(snapshot, PROVEN, PLAIN)
        plain = cast(Solution, unlevered[name])
        assert plain.is_optimal
        assert plain.penalty > 0, f"{name} costs nothing, so nothing can be lost"

        levered = solve(snapshot, PROVEN, lever)

        assert levered.is_optimal
        assert levered.penalty == plain.penalty

    @given(instance=to_score(frozenset(TERMS)), lever=LEVERS)
    @CAREFUL
    def test_no_lever_makes_a_solvable_term_unsolvable(
        self, instance: Instance, lever: Formulation
    ) -> None:
        """Breadth rather than depth, and honest about which it is.

        Generated terms rarely have interchangeable rooms and never cost anything at their
        optimum, so this cannot say the *score* survives. What it can say is that the terms
        which had a timetable still have one — over every kind of rule the generator produces,
        which the two shapes above do not cover.
        """
        snapshot = snapshot_of(instance)
        try:
            plain = solve(snapshot, Budget(seconds=10), PLAIN)
        except UnsatisfiableError:
            assume(False)
        assume(plain.solved)

        assert solve(snapshot, Budget(seconds=10), lever).solved


class TestStartingFromWhatIsPlaced:
    def test_the_timetable_in_the_term_is_handed_to_the_search(self) -> None:
        """One value per start and one per candidate room, for every session already placed."""
        placed = department(24, 6, placed=True)
        model = build(placed, Formulation(hint=True))

        expected = len(placed.placements) + sum(
            len(model.candidates[session_id]) for session_id in placed.placements
        )
        assert len(model.cp.proto.solution_hint.vars) == expected

    def test_a_placement_that_no_longer_fits_is_left_out(self) -> None:
        """A room since made too small. Hinting it anyway asks the search to make sense of a
        contradiction; the honest answer is that this session has no starting point."""
        estate = rooms(2)
        estate[1] = estate[1].model_copy(update={"capacity": 1})
        shrunk = term(
            estate,
            sessions=2,
            assignments=(
                Assignment(
                    id=AssignmentId(1), session_id=SessionId(1), start_slot=0, room_id=RoomId(2)
                ),
                Assignment(
                    id=AssignmentId(2), session_id=SessionId(2), start_slot=1, room_id=RoomId(1)
                ),
            ),
        )
        model = build(shrunk, Formulation(hint=True))

        assert len(model.cp.proto.solution_hint.vars) == 2

    def test_nothing_placed_is_nothing_hinted(self) -> None:
        assert not build(term(rooms(2)), Formulation(hint=True)).cp.proto.solution_hint.vars

    def test_the_default_formulation_starts_from_what_is_placed(self) -> None:
        """The default itself, not only the mechanism behind it.

        Every other test here names `hint=True` explicitly, so flipping the default off would
        leave all of them green while the product quietly went back to starting over.
        """
        placed = department(24, 6, placed=True)

        assert build(placed).cp.proto.solution_hint.vars

    def test_it_is_advice_and_not_a_floor(self) -> None:
        """Written because the obvious claim — *the incumbent is a floor* — is false, and was
        asserted here for an hour before being checked.

        A hint is not a constraint. Given too little work to reach any timetable, a solve
        handed a complete valid one still comes back with nothing: it never got far enough to
        evaluate what it was given. #225 saw the same thing from the other side, where a hint
        did not rescue a department-scale solve either, and part 2 saw it again in the loop,
        where a round with a window of forty returns no answer rather than a worse one.
        """
        term = department(500, 40, placed=True)
        starved = Budget(seconds=300, deterministic_seconds=0.5, rounds=0)

        assert not solve(term, starved, Formulation(hint=True)).solved
        assert not solve(term, starved, PLAIN).solved


@pytest.mark.benchmark
@pytest.mark.skipif(
    not (Path(os.environ.get("TESSERA_ITC2007_INSTANCES", "/nowhere")) / "comp11.ctt").exists(),
    reason="set TESSERA_ITC2007_INSTANCES to the ITC-2007 directory",
)
def test_re_optimising_a_real_instance_beats_starting_over() -> None:
    """The measured claim, on the instance that showed it.

    `comp11` solved from nothing scores 1395. Put that timetable back into the term and solve
    again on the same budget: without the hint the answer is **1618** — worse than what it was
    handed — and with it, 1395.

    Reproducible rather than lucky: one worker, a pinned seed and a deterministic budget, so
    the same three numbers come back on any machine (#231). It needs the 272 KB download, so
    it skips in CI for the same reason the CB-CTT sweep does.
    """
    instance = Path(os.environ["TESSERA_ITC2007_INSTANCES"]) / "comp11.ctt"
    budget = Budget(seconds=900, deterministic_seconds=25.0)

    term = cbctt(instance)
    first = solve(term, budget, PLAIN)
    assert first.solved

    again = with_timetable(term, first.placements)
    starting_over = solve(again, budget, PLAIN)
    hinted = solve(again, budget, Formulation(hint=True))

    assert starting_over.penalty > first.penalty, "the instance no longer shows the defect"
    assert hinted.penalty <= first.penalty
    assert hinted.penalty < starting_over.penalty


class TestABudgetMeasuredInWorkRatherThanTime:
    """D4. A pinned seed and one worker make a solve reproducible on *this* machine; the wall
    clock decides when it stops, so a slower machine gets a different answer. CP-SAT counts its
    own progress in a unit that does not depend on the afternoon, and capping that instead is
    what lets 4.5 gate on a number rather than on a range."""

    def test_the_same_work_budget_gives_the_same_timetable(self) -> None:
        snapshot = department(60, 8)
        budget = Budget(seconds=300, deterministic_seconds=2.0, rounds=0)
        first = solve(snapshot, budget)
        again = solve(snapshot, budget)

        assert first.work == again.work
        assert first.placements == again.placements
        assert first.penalty == again.penalty

    def test_the_wall_clock_is_not_what_stopped_it(self) -> None:
        """Otherwise the deterministic budget is decoration on a stopwatch."""
        found = solve(department(60, 8), Budget(seconds=300, deterministic_seconds=2.0, rounds=0))

        assert found.seconds < 300

    def test_a_smaller_budget_does_less_work(self) -> None:
        """The anti-vacuity guard: a parameter nothing reads would pass both tests above.

        `rounds=0` keeps this about the one solve it is about. A deterministic budget caps
        each *solve*; the outer loop keeps going while the clock allows, so leaving it to run
        would compare two loops rather than two budgets.
        """
        snapshot = department(60, 8)
        brief = solve(snapshot, Budget(seconds=300, deterministic_seconds=1.0, rounds=0))
        longer = solve(snapshot, Budget(seconds=300, deterministic_seconds=6.0, rounds=0))

        assert brief.work < longer.work


class TestTheInstrumentDoesNotFlatterAnything:
    def test_a_solve_that_found_nothing_is_not_printed_as_a_perfect_score(self) -> None:
        """`Solution` refuses to score a failed solve (#205), so it carries penalty 0, bound 0
        and gap 0 — which in a table of scores are the best numbers on the page. The
        formulation that gave up would win the comparison it lost."""
        from tests.solver.comparison import Run, table

        gave_up = Run(
            name="plain",
            outcome=Outcome.OUT_OF_TIME,
            penalty=0,
            bound=0,
            seconds=30.0,
            work=4.1,
            built=2.1,
            variables=182694,
            sessions=500,
            candidates=20000,
        )
        printed = table({"dept(500,40)": (gave_up,)})

        assert "| out_of_time | — | — | — |" in printed
        assert "| 0 | 0 | 0 |" not in printed

    def test_a_solve_that_found_something_is_printed_with_its_numbers(self) -> None:
        from tests.solver.comparison import Run, table

        solved = Run(
            name="plain",
            outcome=Outcome.SOLVED,
            penalty=12,
            bound=12,
            seconds=1.7,
            work=3.3,
            built=0.1,
            variables=7226,
            sessions=24,
            candidates=144,
        )

        assert "| solved (optimal) | 12 | 12 | 0 |" in table({"dept(24,6)": (solved,)})


@pytest.mark.slow
class TestTheInstrumentMeasuresWhatItSaysItDoes:
    def test_the_variable_count_includes_the_objective(self) -> None:
        """#225 is a finding about the objective's size. A count taken after `build` and
        before `add` reports 20,500 where the solver is searching 470,000."""
        from tests.solver.comparison import measure

        scored = measure(department(24, 6), name="scored", budget=Budget(seconds=10))
        bare = measure(department(24, 6, constraints=()), name="bare", budget=Budget(seconds=10))

        assert scored.variables > bare.variables * 5
