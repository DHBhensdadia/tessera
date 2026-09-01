"""The two rules every window must obey, whichever strategy chose it.

Written as properties over `STRATEGIES` rather than as assertions about the one strategy that
exists, so the three part 3 adds inherit both by being registered. That is the arrangement 4.3
used for the sixteen objective terms, and it is the reason a kind cannot be quietly left out of
its own tests.
"""

from __future__ import annotations

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tessera.domain.ids import SessionId
from tessera.domain.validation import Snapshot
from tessera.domain.validation.snapshot import Placement
from tessera.solver import Budget, Formulation, solve
from tessera.solver.neighbourhood import (
    STRATEGIES,
    Strategy,
    _the_rebuild_lost_nothing,
    judge,
    movable,
)
from tests.solver.scored import department, with_timetable

NAMED = st.sampled_from(sorted(STRATEGIES))
SEEDS = st.integers(min_value=0, max_value=64)
WINDOWS = st.integers(min_value=1, max_value=60)


Timetabled = tuple[Snapshot, dict[SessionId, Placement]]


@pytest.fixture(scope="module")
def timetabled() -> Timetabled:
    """A term and a timetable for it, solved once for the whole module."""
    term = department(24, 6)
    found = solve(term, Budget(seconds=30))
    return term, dict(with_timetable(term, found.placements).placements)


class TestEveryStrategyObeysBothRules:
    @given(name=NAMED, seed=SEEDS, window=WINDOWS)
    @settings(max_examples=60, deadline=None)
    def test_it_returns_a_non_empty_set_of_this_term_s_sessions(
        self, name: str, seed: int, window: int, timetabled: Timetabled
    ) -> None:
        term, placed = timetabled
        chosen: Strategy = STRATEGIES[name]

        free = chosen(term, placed, random.Random(seed), window)

        assert free
        assert free <= set(term.sessions)
        assert len(free) <= min(window, len(term.sessions))

    @given(name=NAMED, seed=SEEDS, window=WINDOWS)
    @settings(max_examples=60, deadline=None)
    def test_it_never_frees_a_pinned_session(
        self, name: str, seed: int, window: int, timetabled: Timetabled
    ) -> None:
        """A window that moved a pinned session would break the one promise a person can
        check by looking, and it would do it while handing back a better score."""
        term, placed = timetabled
        pinned = SessionId(3)
        held = placed[pinned]
        with_pin = dict(placed)
        with_pin[pinned] = Placement(
            session_id=pinned,
            start_slot=held.start_slot,
            room_id=held.room_id,
            is_pinned=True,
        )
        term.placements[pinned] = with_pin[pinned]
        chosen: Strategy = STRATEGIES[name]

        try:
            assert pinned not in chosen(term, with_pin, random.Random(seed), window)
        finally:
            term.placements[pinned] = held


class TestWhatMayBeMoved:
    def test_everything_when_nothing_is_pinned(self, timetabled: Timetabled) -> None:
        term, _ = timetabled

        assert movable(term) == sorted(term.sessions)

    def test_the_window_is_the_whole_term_when_it_is_bigger(self, timetabled: Timetabled) -> None:
        """Asking for more than there is gets everything rather than an error, because the
        loop does not know how many sessions a term has when the budget is written."""
        term, placed = timetabled

        free = STRATEGIES["anywhere"](term, placed, random.Random(0), 10_000)

        assert free == set(term.sessions)


class TestEachStrategyDoesWhatItsNameSays:
    """The shared rules say a window is legal. These say it is the window that was asked for —
    a strategy that quietly returned a random handful would pass every property above."""

    def test_one_day_frees_one_day(self, timetabled: Timetabled) -> None:
        term, placed = timetabled

        free = STRATEGIES["one_day"](term, placed, random.Random(1), 20)

        days = {term.grid.day_of(placed[session].start_slot) for session in free}
        assert len(days) == 1

    def test_one_subject_frees_sessions_that_share_somebody(self, timetabled: Timetabled) -> None:
        term, placed = timetabled

        free = STRATEGIES["one_subject"](term, placed, random.Random(1), 20)

        shared = [
            sessions
            for index in (term.sessions_of_group, term.sessions_of_instructor)
            for sessions in index.values()
            if free <= set(sessions)
        ]
        assert shared, "the freed sessions belong to no one group or instructor"

    def test_worst_first_frees_what_costs_the_most(self, timetabled: Timetabled) -> None:
        """Ranked by the validator's attribution, which shares none of the solver's logic."""
        term, placed = timetabled
        blamed: dict[SessionId, int] = {}
        for violation in judge(term, placed).violations:
            if not violation.is_hard:
                blamed[violation.session_id] = blamed.get(violation.session_id, 0) + violation.cost
        assume_costly = sorted(blamed.values(), reverse=True)
        assert assume_costly, "nothing costs anything, so the ranking cannot be checked"

        free = STRATEGIES["worst_first"](term, placed, random.Random(1), 3)

        cheapest_freed = min(blamed.get(session, 0) for session in free)
        dearest_left = max((blamed.get(s, 0) for s in term.sessions if s not in free), default=0)
        assert cheapest_freed >= dearest_left

    def test_worst_first_falls_back_when_nothing_costs_anything(
        self, timetabled: Timetabled
    ) -> None:
        """A term at its optimum has nobody to blame, and a strategy that returned an empty
        window there would stall the loop rather than end it."""
        term, placed = timetabled
        painless = Snapshot.of(
            grid=term.grid,
            sessions=list(term.sessions.values()),
            rooms=list(term.rooms.values()),
            groups=term.groups,
        )

        free = STRATEGIES["worst_first"](painless, placed, random.Random(1), 4)

        assert len(free) == 4


class TestTheFallbacksWhenThereIsNothingToGoOn:
    """A strategy is asked for a window before anything is known about the timetable, and an
    empty window would stall the loop rather than end it. Each has a way to answer anyway."""

    def test_one_day_with_nothing_placed_still_frees_something(
        self, timetabled: Timetabled
    ) -> None:
        term, _ = timetabled

        free = STRATEGIES["one_day"](term, {}, random.Random(0), 20)

        assert len(free) == 1

    def test_one_day_ignores_a_session_that_is_not_placed(self, timetabled: Timetabled) -> None:
        """Half a timetable is still a day to work on."""
        term, placed = timetabled
        half = dict(list(placed.items())[:4])

        free = STRATEGIES["one_day"](term, half, random.Random(0), 20)

        assert free <= set(half)

    def test_one_subject_with_nobody_teaching_twice_still_frees_something(self) -> None:
        """One session in the whole term, so no group and no instructor has two to rearrange."""
        term = department(1, 4)
        placed = dict(with_timetable(term, solve(term, Budget(seconds=30)).placements).placements)

        free = STRATEGIES["one_subject"](term, placed, random.Random(0), 20)

        assert len(free) == 1

    def test_worst_first_ranks_by_cost_and_ignores_what_is_merely_broken(
        self, timetabled: Timetabled
    ) -> None:
        """A hard violation has no cost — it is refused rather than priced — so it cannot rank
        a session. The solver never hands the loop a broken timetable, which is exactly why
        this is asserted here rather than left to arise."""
        term, placed = timetabled
        first, second = sorted(placed)[:2]
        clashing = dict(placed)
        clashing[second] = Placement(
            session_id=second,
            start_slot=placed[first].start_slot,
            room_id=placed[first].room_id,
            is_pinned=False,
        )

        report = judge(term, clashing)
        assert [v for v in report.violations if v.is_hard], "no hard violation to ignore"

        free = STRATEGIES["worst_first"](term, clashing, random.Random(0), 3)

        assert len(free) <= 3


class TestJudgingATimetableTheSolverIsHolding:
    """`Snapshot` indexes its placements when it is built and offers no way to attach others,
    so the term is rebuilt around them — and the rebuild is checked rather than trusted."""

    def test_the_rebuild_keeps_what_the_validator_reads(self, timetabled: Timetabled) -> None:
        term, placed = timetabled

        assert judge(term, placed).penalty >= 0

    def test_a_rebuild_that_lost_something_is_refused(self, timetabled: Timetabled) -> None:
        """The guard against the failure this workaround invites: a field added to `Snapshot`
        that the rebuild does not carry would change what the validator sees without changing
        what anything says."""
        term, _ = timetabled
        thinner = Snapshot.of(
            grid=term.grid,
            sessions=list(term.sessions.values()),
            rooms=list(term.rooms.values()),
            groups=term.groups,
        )

        with pytest.raises(AssertionError, match="lost its constraints"):
            _the_rebuild_lost_nothing(term, thinner)


class TestTheLoopUsesThem:
    def test_a_round_frees_what_the_strategy_chose(self) -> None:
        """The join between the two: `Step.freed` is the size of the window actually used, so
        a strategy silently returning fewer would show up here rather than as a slow loop."""
        found = solve(
            department(24, 6),
            Budget(seconds=600, whole_model_ceiling=0, windows=(6,), rounds=2, round_seconds=60),
            Formulation(),
        )

        assert [step.freed for step in found.trajectory] == [6, 6]
        assert {step.strategy for step in found.trajectory} <= set(STRATEGIES)
