"""What a person watching a solve is told, and when.

4.4 built `on_improvement` and called it *"one emission point for 4.7"*. It is the right
emission point for a listener that stores timetables — its scores strictly decrease and it
fires once per accepted round — and 4.7 measured that it is not a progress stream. On three
real terms at a thirty-second budget it emitted once, eleven times, and **not at all**; on the
last of those the solver worked for half a minute and returned a good timetable having said
nothing whatsoever.

So there are two callbacks with two different promises, and these tests are about the second.
"""

from __future__ import annotations

import pytest

from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Progress, Solution, solve
from tests.solver.scored import department

#: Long enough for the unrestricted attempt to be the whole story, which is the shape §1a
#: found: the loop never reaches an accepted round and `on_improvement` never fires.
BRIEF = Budget(seconds=10.0)


def watched(term: Snapshot, budget: Budget = BRIEF) -> tuple[list[Progress], list[int], Solution]:
    progress: list[Progress] = []
    improvements: list[int] = []
    found = solve(
        term,
        budget,
        on_progress=progress.append,
        on_improvement=lambda answer: improvements.append(answer.penalty),
    )
    return progress, improvements, found


@pytest.mark.slow
class TestTheStreamIsNeverSilent:
    def test_something_is_said_before_any_round_is_accepted(self) -> None:
        """The finding of 4.7 §1a, as a test.

        On a hundred and fifty sessions the model fits under the whole-model ceiling, so the
        one unrestricted attempt runs for the entire clock and the loop reaches no round at
        all. A panel fed by accepted rounds draws nothing for ten seconds; this asserts there
        are at least two things to draw before the first of them.
        """
        progress, improvements, _ = watched(department(150, 12))

        assert len(progress) >= len(improvements) + 2

    def test_a_valid_timetable_is_announced_before_anybody_has_priced_it(self) -> None:
        """P7 draws *"Feasible solution found in 6s"* as its own line, and it is genuinely
        earlier than any score: the feasibility pass produces a timetable and the loop is what
        prices it, which is a whole model build later — 5.10 s against 7.93 s at department
        scale."""
        progress, _, _ = watched(department(150, 12))

        assert progress[0].phase == "feasibility"
        assert progress[0].penalty is None

    def test_and_then_what_it_costs(self) -> None:
        """The incumbent's own score, which nothing emitted before this phase.

        `on_improvement` is silent about it by design — it is the thing improvements are
        measured against rather than an improvement — so the first number a person saw used to
        be whatever the search reached, if it reached anything.
        """
        progress, _, _ = watched(department(150, 12))

        assert progress[1].phase == "optimising"
        assert progress[1].penalty is not None
        assert progress[1].penalty > 0

    def test_a_term_that_prices_nothing_still_reports_its_zero(self) -> None:
        """Nothing to optimise is an answer, not an absence."""
        progress, _, found = watched(department(24, 6, constraints=()), Budget(seconds=5.0))

        assert found.penalty == 0
        assert [event.penalty for event in progress] == [None, 0]


@pytest.mark.slow
class TestWhatTheStreamPromises:
    def test_the_score_never_rises(self) -> None:
        """The one thing a panel promising *"watch it get better"* may not do.

        It is not free: a round is handed the incumbent as a hint, and CP-SAT's first solution
        inside it can be worse than what went in before it improves. `_Reporter` is what makes
        the stream monotone whatever produced the number.
        """
        progress, _, _ = watched(department(40, 6), Budget(seconds=8.0))

        scored = [event.penalty for event in progress if event.penalty is not None]
        assert scored == sorted(scored, reverse=True)
        assert len(set(scored)) == len(scored)

    def test_the_clock_only_moves_forwards(self) -> None:
        progress, _, _ = watched(department(40, 6), Budget(seconds=8.0))

        assert [event.seconds for event in progress] == sorted(event.seconds for event in progress)

    def test_a_bound_is_reported_only_once_something_has_proved_one(self) -> None:
        """4.4's D6, on the wire this time.

        A Fix-and-Optimize round bounds its own window and not the term, so with the
        unrestricted attempt switched off there is nothing that could prove a bound — and
        `None` rather than zero is what says so.
        """
        progress, _, _ = watched(
            department(150, 12), Budget(seconds=10.0, whole_model_ceiling=0, windows=(8,))
        )

        assert [event.lower_bound for event in progress] == [None] * len(progress)

    def test_every_event_counts_the_answers_seen_so_far(self) -> None:
        progress, _, _ = watched(department(40, 6), Budget(seconds=8.0))

        scored = [event.solutions for event in progress if event.penalty is not None]
        assert scored == list(range(1, len(scored) + 1))


#: Budgeted in work rather than in seconds, because the claim is that two runs agree and
#: whether a wall-clock run reaches the same place twice is a fact about the machine (#231,
#: #244). Four rounds of one deterministic unit each land in the same place on any hardware.
REPRODUCIBLE = Budget(
    seconds=600,
    whole_model_ceiling=0,
    windows=(6,),
    rounds=4,
    round_seconds=60,
    round_deterministic_seconds=1.0,
)


@pytest.mark.slow
def test_a_listener_is_optional_and_the_search_does_not_notice_one() -> None:
    """The guard for attaching a CP-SAT callback to every solve.

    With nobody listening no callback is constructed, and with somebody listening the search
    still reaches the same answer — so the benchmark, which passes neither, is running the
    code it always did, and a person watching is not being shown a different solver.
    """
    term = department(24, 6)

    without = solve(term, REPRODUCIBLE)
    with_listener = solve(term, REPRODUCIBLE, on_progress=lambda _: None)

    assert without.penalty == with_listener.penalty
    assert without.work == pytest.approx(with_listener.work, rel=0.05)
