"""The time model.

Time is an **integer slot index**, never a timestamp. A week is
``days x slots_per_day`` consecutive integers, and a session occupying four slots is
``[start, start + 4)``. Overlap detection therefore reduces to integer comparison,
which is both faster and easier to get right than interval arithmetic over dates.

Wall-clock times exist only for display: they are derived here and never stored on an
assignment. Changing ``slot_minutes`` after scheduling would silently reinterpret every
stored assignment, which is why the grid is fixed per term and duplicating a term
copies it rather than sharing it.

See ADR-0005.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tessera.domain.ids import InstitutionId, TimeGridId

# A slot index within a week. Kept as a plain int: it is arithmetic, not an identity.
Slot = int


class TimeGrid(BaseModel):
    """The teaching week: how many days, how finely divided, and where the breaks are.

    ``break_slots`` holds *slot-of-day* indices, not week-absolute slots, because a
    lunch break recurs at the same time every day. Storing the week-absolute form would
    make "move lunch by half an hour" a rewrite of every day.
    """

    model_config = ConfigDict(frozen=True)

    id: TimeGridId | None = None
    institution_id: InstitutionId | None = None
    name: str = "Default"

    days: int = Field(ge=1, le=7)
    slots_per_day: int = Field(ge=1, le=96)
    slot_minutes: int = Field(ge=5, le=120)
    day_start_minute: int = Field(ge=0, lt=24 * 60)
    break_slots: frozenset[int] = frozenset()

    @model_validator(mode="after")
    def _breaks_must_be_within_the_day(self) -> TimeGrid:
        out_of_range = [s for s in self.break_slots if not 0 <= s < self.slots_per_day]
        if out_of_range:
            raise ValueError(
                f"break slots {sorted(out_of_range)} fall outside a day of "
                f"{self.slots_per_day} slots"
            )
        if len(self.break_slots) >= self.slots_per_day:
            raise ValueError("every slot of the day is a break; nothing could be scheduled")
        return self

    @property
    def slot_count(self) -> int:
        """Total slots in the week, including breaks."""
        return self.days * self.slots_per_day

    @property
    def teaching_slots(self) -> tuple[Slot, ...]:
        """Week-absolute slots that are not breaks, in order."""
        return tuple(
            slot
            for slot in range(self.slot_count)
            if self.slot_of_day(slot) not in self.break_slots
        )

    def day_of(self, slot: Slot) -> int:
        return slot // self.slots_per_day

    def slot_of_day(self, slot: Slot) -> int:
        return slot % self.slots_per_day

    def contains(self, slot: Slot) -> bool:
        return 0 <= slot < self.slot_count

    def is_break(self, slot: Slot) -> bool:
        return self.slot_of_day(slot) in self.break_slots

    def span(self, start: Slot, duration: int) -> tuple[Slot, ...]:
        """The slots a session would occupy, or an error if it cannot sit there.

        Rejects three things a naive range would allow: running off the end of the
        week, crossing midnight into the next day, and running through a break. A
        two-hour lab cannot straddle lunch, and expressing that here means neither the
        solver nor the UI has to remember it independently.
        """
        if duration < 1:
            raise ValueError(f"duration must be at least one slot, got {duration}")
        if not self.contains(start):
            raise ValueError(f"slot {start} is outside a week of {self.slot_count} slots")

        end = start + duration
        if self.slot_of_day(start) + duration > self.slots_per_day:
            raise ValueError(
                f"a {duration}-slot session starting at slot {start} would run past the "
                f"end of day {self.day_of(start)}"
            )

        occupied = tuple(range(start, end))
        blocked = [s for s in occupied if self.is_break(s)]
        if blocked:
            raise ValueError(f"slots {blocked} are breaks and cannot be taught through")
        return occupied

    def can_hold(self, start: Slot, duration: int) -> bool:
        """Whether ``span`` would succeed. For filtering candidate placements."""
        try:
            self.span(start, duration)
        except ValueError:
            return False
        return True

    def start_slots_for(self, duration: int) -> tuple[Slot, ...]:
        """Every slot at which a session of this duration could legally begin."""
        return tuple(s for s in range(self.slot_count) if self.can_hold(s, duration))

    # -- display only ------------------------------------------------------------
    # Nothing below is ever persisted on an assignment; it is derived on the way out.

    def minute_of_day(self, slot: Slot) -> int:
        return self.day_start_minute + self.slot_of_day(slot) * self.slot_minutes

    def clock(self, slot: Slot) -> str:
        """``"11:30"`` for the start of the given slot."""
        minute = self.minute_of_day(slot)
        return f"{minute // 60:02d}:{minute % 60:02d}"

    def label(self, slot: Slot, day_names: tuple[str, ...] | None = None) -> str:
        """``"Tue 11:30"``. Day names default to weekdays from Monday."""
        names = day_names or ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        return f"{names[self.day_of(slot) % len(names)]} {self.clock(slot)}"
