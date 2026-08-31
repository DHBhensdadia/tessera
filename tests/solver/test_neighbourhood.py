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
from tessera.solver.neighbourhood import STRATEGIES, Strategy, movable
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


class TestTheLoopUsesThem:
    def test_a_round_frees_what_the_strategy_chose(self) -> None:
        """The join between the two: `Step.freed` is the size of the window actually used, so
        a strategy silently returning fewer would show up here rather than as a slow loop."""
        found = solve(
            department(24, 6),
            Budget(seconds=20, whole_model_ceiling=0, window=6, rounds=2),
            Formulation(),
        )

        assert [step.freed for step in found.trajectory] == [6, 6]
        assert {step.strategy for step in found.trajectory} <= set(STRATEGIES)
