"""The time model.

Slot arithmetic is the foundation the solver and the validator both stand on, so it is
tested with generated inputs rather than only chosen ones: an off-by-one here would
surface much later as a session mysteriously scheduled through lunch.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from tessera.domain import TimeGrid


def make_grid(**overrides: object) -> TimeGrid:
    base: dict[str, object] = {
        "days": 5,
        "slots_per_day": 16,
        "slot_minutes": 30,
        "day_start_minute": 9 * 60,
    }
    return TimeGrid(**(base | overrides))  # type: ignore[arg-type]


class TestStructure:
    def test_a_week_is_days_times_slots(self) -> None:
        assert make_grid().slot_count == 80

    def test_breaks_are_excluded_from_teaching_slots(self) -> None:
        grid = make_grid(break_slots=frozenset({8, 9}))
        # Two break slots on each of five days.
        assert len(grid.teaching_slots) == 80 - 10

    def test_a_break_outside_the_day_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="outside a day"):
            make_grid(break_slots=frozenset({99}))

    def test_a_grid_that_is_entirely_break_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="nothing could be scheduled"):
            make_grid(slots_per_day=2, break_slots=frozenset({0, 1}))


class TestSpans:
    def test_a_session_occupies_consecutive_slots(self) -> None:
        assert make_grid().span(4, 3) == (4, 5, 6)

    def test_a_session_may_not_run_past_the_end_of_a_day(self) -> None:
        grid = make_grid()
        # Slot 15 is the last of Monday; a two-slot session would land on Tuesday.
        with pytest.raises(ValueError, match="past the end of day"):
            grid.span(15, 2)

    def test_a_session_may_not_be_taught_through_a_break(self) -> None:
        grid = make_grid(break_slots=frozenset({8, 9}))
        with pytest.raises(ValueError, match="are breaks"):
            grid.span(6, 4)

    def test_a_session_may_sit_either_side_of_a_break(self) -> None:
        grid = make_grid(break_slots=frozenset({8, 9}))
        assert grid.can_hold(6, 2)
        assert grid.can_hold(10, 2)

    def test_a_slot_outside_the_week_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside a week"):
            make_grid().span(80, 1)

    def test_zero_duration_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one slot"):
            make_grid().span(0, 0)


class TestDisplay:
    def test_clock_derives_from_the_grid(self) -> None:
        grid = make_grid()
        assert grid.clock(0) == "09:00"
        assert grid.clock(8) == "13:00"

    def test_label_names_the_day(self) -> None:
        assert make_grid().label(16) == "Tue 09:00"

    def test_a_finer_grid_reads_differently_for_the_same_index(self) -> None:
        """Slot indices are meaningless without their grid.

        This is exactly why the grid is fixed per term: reinterpreting stored indices
        under a different slot length would silently move every session.
        """
        assert make_grid(slot_minutes=30).clock(2) == "10:00"
        assert make_grid(slot_minutes=15).clock(2) == "09:30"


class TestProperties:
    @given(
        days=st.integers(1, 7),
        slots_per_day=st.integers(1, 24),
        slot=st.integers(0, 200),
    )
    def test_day_and_slot_of_day_reconstruct_the_index(
        self, days: int, slots_per_day: int, slot: int
    ) -> None:
        grid = make_grid(days=days, slots_per_day=slots_per_day)
        if not grid.contains(slot):
            return
        assert grid.day_of(slot) * slots_per_day + grid.slot_of_day(slot) == slot

    @given(
        slots_per_day=st.integers(2, 24),
        duration=st.integers(1, 8),
        breaks=st.sets(st.integers(0, 23), max_size=4),
    )
    def test_every_legal_start_produces_a_legal_span(
        self, slots_per_day: int, duration: int, breaks: set[int]
    ) -> None:
        """``start_slots_for`` and ``span`` must agree in both directions.

        The solver enumerates candidate placements with the former and the validator
        checks them with the latter; if they ever disagree, the solver would propose
        placements the validator rejects.
        """
        valid_breaks = frozenset(b for b in breaks if b < slots_per_day)
        if len(valid_breaks) >= slots_per_day:
            return
        grid = make_grid(slots_per_day=slots_per_day, break_slots=valid_breaks)

        starts = grid.start_slots_for(duration)
        for start in starts:
            occupied = grid.span(start, duration)
            assert len(occupied) == duration
            assert not any(grid.is_break(s) for s in occupied)
            assert len({grid.day_of(s) for s in occupied}) == 1

        illegal = set(range(grid.slot_count)) - set(starts)
        for start in illegal:
            assert not grid.can_hold(start, duration)
