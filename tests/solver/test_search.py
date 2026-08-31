"""The outer search: what it promises, and the ways it could quietly stop keeping the promise.

A Fix-and-Optimize loop is the easiest place in this codebase to produce an improvement that is
really a broken constraint. Freeing a session that was supposed to be frozen makes the score go
down and the timetable wrong, and it arrives in a phase whose whole subject is scores going
down. So the validator judges the answer of **every** round rather than only the last, and the
score the loop reports is checked against the validator's the same way 4.3 checked a single
solve — because the loop is exactly where the two readings could drift apart without either
being wrong on its own.

`whole_model_ceiling=0` appears throughout. It stops the unrestricted attempt from running, so
a small term exercises the loop instead of being answered outright — which is what makes these
tests seconds rather than minutes.
"""

from __future__ import annotations

import time

import pytest

from tessera.domain.constraints import Constraint, ConstraintKind
from tessera.domain.ids import RoomId, SessionId
from tessera.domain.validation import Report, Snapshot, validate
from tessera.solver import Budget, Formulation, Outcome, Placed, Solution, Step, solve
from tessera.solver.model import build
from tessera.solver.objective import add
from tessera.solver.search import _keep_going, _left
from tests.solver.scored import department, with_timetable

#: Small enough to run in the gate, and forced through the loop rather than answered whole.
LOOPED = Budget(seconds=20, whole_model_ceiling=0, window=6, rounds=4)

#: A timetable of one session, for the guards that are about the *numbers* a `Solution` carries.
#: A solved answer with nothing in it is refused first and separately, so a construction meant
#: to trip a later guard has to get past that one.
SOMEWHERE = (Placed(session=SessionId(1), start_slot=0, room=RoomId(1)),)

#: A rule no arrangement of a single-site term can break, so every timetable scores zero.
NOTHING_TO_FIX = Constraint(kind=ConstraintKind.MINIMISE_BUILDING_CHANGES, weight=3)


def verdict(term: Snapshot, found: Solution) -> Report:
    """What the 4.1 validator makes of what the loop produced."""
    return validate(with_timetable(term, found.placements))


@pytest.fixture(scope="module")
def looped() -> Solution:
    """One run of the loop, shared by the tests that only read it."""
    return solve(department(24, 6), LOOPED)


class TestTheLoopRuns:
    def test_it_takes_the_rounds_it_was_given(self, looped: Solution) -> None:
        assert looped.outcome is Outcome.SOLVED
        assert len(looped.trajectory) == 4

    def test_every_round_is_recorded_whether_or_not_it_helped(self, looped: Solution) -> None:
        """A rejected round is as informative as an accepted one — a long tail of refusals is
        what a window too big to solve looks like from outside, and it is what this loop's
        first department-scale run actually did."""
        assert [step.round for step in looped.trajectory] == [0, 1, 2, 3]
        assert all(step.freed > 0 for step in looped.trajectory)

    def test_a_round_reports_what_it_cost_even_when_it_found_nothing(self) -> None:
        """#235's shape again: a round that gave up must not look like the cheap one."""
        starved = solve(
            department(24, 6),
            Budget(seconds=20, whole_model_ceiling=0, rounds=1, window=6, round_seconds=0.0),
        )

        assert starved.trajectory[0].accepted is False
        assert starved.trajectory[0].seconds >= 0.0


class TestAModelTheSolverWillNotReadIsABug:
    """The guard that cost a suite run to learn the need for.

    `Formulation.hint` is on by default, so a sub-model built with it hints the term's own
    placements — and then the loop hints the incumbent over the top. CP-SAT answers a variable
    hinted twice with `MODEL_INVALID`, `_run` saw "not a solution" and reported a round that
    found nothing, and the loop reported that it had simply failed to improve. Forty-one tests
    in another module went red and this one stayed green.
    """

    def test_a_duplicated_hint_is_refused_rather_than_read_as_a_bad_round(self) -> None:
        from tessera.solver.model import start_from
        from tessera.solver.search import _run

        term = department(24, 6)
        first = solve(term, Budget(seconds=30))
        placed = with_timetable(term, first.placements).placements

        model = build(term, Formulation(hint=True), placed)
        objective = add(model, term)
        assert objective is not None
        start_from(model, placed)

        with pytest.raises(AssertionError, match="not a valid model"):
            _run(
                model,
                objective,
                start_from=placed,
                budget=Budget(seconds=5),
                seconds=5.0,
                deterministic=None,
            )

    def test_the_loop_builds_its_sub_problems_without_the_term_s_hint(self) -> None:
        """The fix, asserted where it is made rather than only in its consequence: a term that
        already has a timetable is exactly the case that broke, and it must now loop."""
        term = department(24, 6)
        first = solve(term, Budget(seconds=30))

        found = solve(with_timetable(term, first.placements), LOOPED)

        assert found.trajectory
        assert found.outcome is Outcome.SOLVED


class TestWhenTheLoopShouldStop:
    """The rule that turned a thirty-seven minute suite back into a three minute one.

    Every scored term is a sum of non-negative units, so a timetable costing nothing is optimal
    and no rearrangement can beat it. Without that, the loop treated *"the budget has not run
    out"* as *"there is work to do"* and spent three hundred seconds and a hundred and fifty
    rounds on a term it had already finished — a busy wait wearing anytime behaviour's clothes.
    """

    def test_a_timetable_that_costs_nothing_ends_it(self) -> None:
        """A rule no arrangement can break — building changes on a single site — so the first
        timetable found already costs nothing and there is nothing for a round to do."""
        term = department(24, 6, constraints=(NOTHING_TO_FIX,))

        found = solve(term, Budget(seconds=120, whole_model_ceiling=0, window=6))

        assert found.penalty == 0
        assert found.trajectory == ()
        assert found.seconds < 120

    def test_but_a_cost_above_zero_does_not(self) -> None:
        assert _keep_going(Budget(seconds=300, rounds=9), time.perf_counter(), 0, 1) is True
        assert _keep_going(Budget(seconds=300, rounds=9), time.perf_counter(), 0, 0) is False

    def test_a_round_count_outranks_the_clock(self) -> None:
        """Otherwise a slow machine gives back the reproducibility the count was asked for."""
        assert _keep_going(Budget(seconds=300, rounds=2), time.perf_counter(), 1, 5) is True
        assert _keep_going(Budget(seconds=300, rounds=2), time.perf_counter(), 2, 5) is False

    def test_and_without_one_the_clock_decides(self) -> None:
        spent = time.perf_counter() - 299
        assert _keep_going(Budget(seconds=300, round_seconds=5.0), spent, 0, 5) is False

    def test_the_clock_it_watches_stops_before_the_budget_does(self) -> None:
        """A budget of thirty seconds that answers at 30.013 is not thirty seconds.

        CP-SAT's time limit is a target rather than a guarantee, and a round that stops on time
        still has to be read back and scored, so the loop aims at a deadline slightly inside
        the one it was given.
        """
        budget = Budget(seconds=10.0, round_seconds=1.0)

        assert _left(budget, time.perf_counter()) < budget.seconds
        assert _left(budget, time.perf_counter() - 9.7) < 0


class TestTheDescentIsMonotone:
    """D5. The incumbent is a feasible point of every sub-problem — the frozen sessions are
    already where they are and the free ones may simply stay — so a round cannot come back
    above it. That is a theorem about the arrangement rather than a policy applied to it."""

    def test_the_score_never_rises(self, looped: Solution) -> None:
        accepted = [step.penalty for step in looped.trajectory if step.accepted]

        assert accepted == sorted(accepted, reverse=True)
        assert len(set(accepted)) == len(accepted)

    def test_the_answer_is_the_last_accepted_round(self, looped: Solution) -> None:
        """Two numbers about one timetable, and no way to tell which is the timetable."""
        accepted = [step for step in looped.trajectory if step.accepted]
        if accepted:
            assert accepted[-1].penalty == looped.penalty

    def test_a_round_that_matched_the_incumbent_is_refused(self) -> None:
        """The acceptance rule itself, which nothing else here can see fail.

        Every round is hinted with the incumbent and minimises, so it comes back at or below
        what it started with and *accept anything* looks identical to *accept an improvement*
        — a mutation replacing one with the other passed seven tests. The two only differ when
        a round comes back **equal**, so this starts the loop on a timetable already at its
        proven optimum: every round then matches, every round must be refused, and accepting
        them would make the trajectory non-decreasing and `Solution` would refuse it.
        """
        term = department(24, 6)
        best = solve(term, Budget(seconds=30))
        assert best.is_optimal and best.penalty > 0

        found = solve(with_timetable(term, best.placements), LOOPED)

        assert found.penalty == best.penalty
        assert [step.accepted for step in found.trajectory] == [False] * len(found.trajectory)
        assert found.trajectory, "no round ran, so nothing was refused"

    def test_a_trajectory_that_went_up_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not an improvement"):
            Solution(
                outcome=Outcome.SOLVED,
                placements=SOMEWHERE,
                trajectory=(
                    Step(
                        round=0,
                        strategy="anywhere",
                        freed=4,
                        penalty=10,
                        seconds=1.0,
                        accepted=True,
                    ),
                    Step(
                        round=1,
                        strategy="anywhere",
                        freed=4,
                        penalty=12,
                        seconds=1.0,
                        accepted=True,
                    ),
                ),
            )

    def test_an_answer_that_is_not_the_last_accepted_round_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not the same timetable"):
            Solution(
                outcome=Outcome.SOLVED,
                placements=SOMEWHERE,
                penalty=7,
                penalty_breakdown={"minimise_group_gaps": 7},
                trajectory=(
                    Step(
                        round=0,
                        strategy="anywhere",
                        freed=4,
                        penalty=10,
                        seconds=1.0,
                        accepted=True,
                    ),
                ),
            )


class TestEveryRoundLeavesAValidTimetable:
    def test_the_answer_is_feasible_and_complete(self, looped: Solution) -> None:
        judged = verdict(department(24, 6), looped)

        assert judged.is_feasible
        assert judged.is_complete
        assert [v for v in judged.violations if v.is_hard] == []

    def test_and_so_is_every_improvement_along_the_way(self) -> None:
        """Not only at the end. A round that quietly freed a frozen session would score better
        and be wrong, and the last round is the one least likely to show it."""
        term = department(24, 6)
        seen: list[Report] = []
        solve(term, LOOPED, on_improvement=lambda s: seen.append(verdict(term, s)))

        assert seen, "no improvement was emitted, so nothing was checked"
        assert all(report.is_feasible and report.is_complete for report in seen)


class TestTheScoreStillAgreesWithTheValidator:
    """4.3's exit test, re-run on what the loop produced. The loop is where the two readings
    could come apart without either being wrong about a single solve."""

    def test_the_penalty_is_the_validator_s_penalty(self, looped: Solution) -> None:
        assert looped.penalty == verdict(department(24, 6), looped).penalty

    def test_and_so_is_every_line_of_the_breakdown(self, looped: Solution) -> None:
        assert looped.penalty_breakdown == verdict(department(24, 6), looped).penalty_breakdown


class TestAnUnprovenWholeAttempt:
    def test_it_sets_the_bound_and_the_loop_carries_on(self) -> None:
        """The whole problem can be solved without being *finished*: CP-SAT returns the best
        it reached and a bound it could not close. That bound is real — an unrestricted solve
        proved it — and the rounds that follow must not overwrite it with their own."""
        found = solve(
            department(60, 8),
            Budget(seconds=120, deterministic_seconds=8.0, rounds=1, window=8),
        )
        whole = [step for step in found.trajectory if step.freed == 0]

        assert whole, "the whole problem was never attempted"
        assert found.bound_is_proven is True
        assert found.lower_bound <= found.penalty
        assert found.is_optimal is False


class TestTheBoundHasProvenance:
    """D6. A round bounds its own window, which is a different and easier problem."""

    def test_a_loop_that_never_solved_the_whole_thing_claims_no_bound(
        self, looped: Solution
    ) -> None:
        assert looped.bound_is_proven is False
        assert looped.lower_bound == 0

    def test_an_unrestricted_solve_does_claim_one(self) -> None:
        whole = solve(department(24, 6), Budget(seconds=30))

        assert whole.bound_is_proven is True
        assert whole.is_optimal

    def test_a_bound_nothing_proved_is_refused(self) -> None:
        """The guard that `_the_score_makes_sense` could not give: a sub-problem's bound is at
        or below the incumbent's penalty, so every other check passes."""
        with pytest.raises(ValueError, match="nothing having proven it"):
            Solution(
                outcome=Outcome.SOLVED,
                placements=SOMEWHERE,
                penalty=10,
                penalty_breakdown={"minimise_group_gaps": 10},
                lower_bound=4,
                bound_is_proven=False,
            )


class TestTheLoopRespectsAPin:
    def test_a_pinned_session_is_never_freed(self) -> None:
        """Decision #10 put `is_pinned` in the schema on the first day so that re-optimising
        around manual edits would not need a solver rewrite. A window that moved one would
        turn that into a lie in the one place nobody looks — the timetable came back better."""
        term = department(24, 6)
        first = solve(term, Budget(seconds=30))
        pinned = SessionId(3)
        held = next(p for p in first.placements if p.session == pinned)

        again = with_timetable(term, first.placements)
        again.placements[pinned] = type(again.placements[pinned])(
            session_id=pinned,
            start_slot=held.start_slot,
            room_id=held.room,
            is_pinned=True,
        )
        again._index(again.placements[pinned])

        found = solve(again, LOOPED)
        landed = next(p for p in found.placements if p.session == pinned)

        assert (landed.start_slot, landed.room) == (held.start_slot, held.room)


class TestFreezingByNarrowingTheDomain:
    """D3, and the measurement the whole loop rests on."""

    def test_a_frozen_session_has_one_hour_and_one_room(self) -> None:
        term = department(24, 6)
        first = solve(term, Budget(seconds=30))
        placed = with_timetable(term, first.placements).placements

        model = build(term, Formulation(), placed)

        assert all(len(hours) == 1 for hours in model.legal.values())
        assert all(len(rooms) == 1 for rooms in model.candidates.values())

    def test_a_frozen_model_is_far_smaller_than_the_whole_one(self) -> None:
        """Freezing by adding equalities would leave the model exactly as large and simply
        forbid most of it. This is the difference, and it is the reason a round is affordable."""
        term = department(24, 6)
        first = solve(term, Budget(seconds=30))
        placed = with_timetable(term, first.placements).placements

        whole = build(term, Formulation())
        add(whole, term)
        frozen = build(term, Formulation(), placed)
        add(frozen, term)

        assert len(frozen.cp.proto.variables) * 3 < len(whole.cp.proto.variables)

    def test_a_frozen_session_stays_where_it_was_put(self) -> None:
        term = department(24, 6)
        first = solve(term, Budget(seconds=30))
        placed = with_timetable(term, first.placements).placements
        held = {s: (p.start_slot, p.room_id) for s, p in placed.items()}

        model = build(term, Formulation(), placed)

        assert {s: (model.legal[s][0], model.candidates[s][0].room) for s in held} == held


class TestTheCallback:
    """D8. 4.7 turns this into an SSE stream, so the loop has one emission point rather than
    the interface reaching in to find its own."""

    def test_it_fires_once_per_accepted_round(self) -> None:
        term = department(24, 6)
        seen: list[int] = []
        found = solve(term, LOOPED, on_improvement=lambda s: seen.append(s.penalty))

        assert seen == [step.penalty for step in found.trajectory if step.accepted]

    def test_it_never_fires_for_a_round_that_changed_nothing(self) -> None:
        term = department(24, 6)
        seen: list[int] = []
        found = solve(term, LOOPED, on_improvement=lambda s: seen.append(s.penalty))

        assert len(seen) < len(found.trajectory) or all(s.accepted for s in found.trajectory)
        assert len(set(seen)) == len(seen)

    def test_a_loop_with_no_listener_still_runs(self, looped: Solution) -> None:
        assert looped.trajectory


class TestABudgetCountedInRounds:
    """D4. How many rounds fit in thirty seconds depends on the machine; how many rounds were
    asked for does not."""

    def test_the_wall_clock_is_not_what_stopped_it(self) -> None:
        found = solve(
            department(24, 6),
            Budget(
                seconds=300,
                whole_model_ceiling=0,
                window=6,
                rounds=3,
                round_deterministic_seconds=1.0,
            ),
        )

        assert len(found.trajectory) == 3
        assert found.seconds < 300

    def test_the_same_budget_twice_gives_the_same_timetable(self) -> None:
        budget = Budget(
            seconds=300, whole_model_ceiling=0, window=6, rounds=3, round_deterministic_seconds=1.0
        )
        term = department(24, 6)

        assert solve(term, budget).placements == solve(term, budget).placements


@pytest.fixture(scope="module")
def at_scale() -> Solution:
    """One department-scale run, shared. Thirty seconds is the claim; three of them is waste."""
    return solve(department(500, 40), Budget(seconds=30))


@pytest.mark.slow
class TestWhatPartTwoIsFor:
    """#225, answered. Five hundred sessions, forty rooms, a hundred-hour week, and the
    preferences a new term actually starts with — `default_constraints()`, group gaps at 8 and
    instructor gaps at 5, which is the configuration and not an exotic one.

    Before this part, that term produced **nothing at all** in thirty seconds: three of the
    sixteen scored terms need a boolean per subject per hour, the model is 182,694 variables
    against feasibility's 20,500, and the search never reached a first answer. Part 1 measured
    it again under all four formulations and none of them moved it.
    """

    def test_a_department_with_the_default_preferences_is_scored_and_improved(
        self, at_scale: Solution
    ) -> None:
        found = at_scale

        assert found.outcome is Outcome.SOLVED, "the whole point of the part"
        assert found.seconds < 30
        assert found.trajectory, "no rounds ran, so nothing was optimised"

        accepted = [step for step in found.trajectory if step.accepted]
        assert accepted, "every round was refused — the window is too big to solve"
        assert found.penalty < accepted[0].penalty or len(accepted) == 1

    def test_and_the_validator_agrees_with_every_word_of_it(self, at_scale: Solution) -> None:
        """Feasible, complete, and scored the same by the reading that shares none of the
        solver's logic. A round that freed a frozen session would score better and be wrong."""
        found = at_scale
        judged = verdict(department(500, 40), found)

        assert judged.is_feasible
        assert judged.is_complete
        assert [v for v in judged.violations if v.is_hard] == []
        assert found.penalty == judged.penalty
        assert found.penalty_breakdown == judged.penalty_breakdown

    def test_it_claims_no_lower_bound_it_did_not_earn(self, at_scale: Solution) -> None:
        """The model is over the ceiling, so nothing solved the whole problem and nothing may
        claim to have bounded it (D6)."""
        found = at_scale

        assert found.bound_is_proven is False
        assert found.lower_bound == 0
        assert found.is_optimal is False
