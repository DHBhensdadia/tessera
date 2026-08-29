"""What Tessera can hold of an instance, and what the ledger says about the rest.

The mapping is the lossy step, so these tests are mostly about the loss being *stated*. A
mapping that quietly dropped 52,254 classes would pass any test asking only whether the rooms
arrived — and the fidelity report built on it in part 3 would be wrong with numbers in it,
which is worse than being wrong without.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera.importers.itc import Instance, read
from tessera.importers.itc.apply import (
    COUNTERPARTS,
    MAX_SLOTS_PER_DAY,
    Entry,
    Fate,
    Grid,
    course_code,
    mapped,
    room_name,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def bet() -> Instance:
    return read(FIXTURES / "bet-sum18.xml")


@pytest.fixture(scope="module")
def purdue() -> Instance:
    return read(FIXTURES / "pu-cs-fal07.xml")


class TestChoosingAGrid:
    def test_the_finest_that_fits(self, bet: Instance) -> None:
        """`bet-sum18` teaches 08:00 to 16:50. At five-minute slots that is 106, over the
        domain's ceiling of 96; at ten it is 53, so ten it is."""
        grid = Grid.for_(bet)

        assert grid.slot_minutes == 10
        assert grid.slots_per_day == 53
        assert grid.day_start_minute == 8 * 60
        assert grid.days == 7

    def test_the_day_is_the_teaching_day(self, purdue: Instance) -> None:
        """Not ITC's midnight-to-midnight day. Narrowing it is what buys the precision."""
        grid = Grid.for_(purdue)

        assert grid.day_start_minute == 7 * 60 + 30
        assert grid.slot_minutes == 10

    def test_no_instance_gets_five_minute_slots(self, bet: Instance, purdue: Instance) -> None:
        """The headline loss, and the one that cannot be avoided without changing the
        domain — which D2 rules out. ITC states every time to five minutes."""
        assert not Grid.for_(bet).is_exact
        assert not Grid.for_(purdue).is_exact

    def test_it_never_exceeds_what_the_domain_allows(self, bet: Instance, purdue: Instance) -> None:
        for instance in (bet, purdue):
            assert Grid.for_(instance).slots_per_day <= MAX_SLOTS_PER_DAY

    def test_the_grid_it_produces_is_one_the_domain_accepts(self, bet: Instance) -> None:
        """Built through the real `TimeGrid`, so its validators run. A grid this module
        invented but the domain would reject is a failure that would otherwise surface
        only when somebody tried to import."""
        grid = Grid.for_(bet).to_domain()

        assert grid.slots_per_day == 53
        assert grid.slot_count == 7 * 53


class TestMovingATimeOntoIt:
    @pytest.fixture
    def grid(self) -> Grid:
        """Ten-minute slots from 08:00, which is `bet-sum18`'s."""
        return Grid(days=7, slots_per_day=53, slot_minutes=10, day_start_minute=480)

    def test_a_time_that_lands_exactly(self, grid: Grid) -> None:
        """ITC slot 102 is 08:30, which is slot 3 of a ten-minute day starting at 08:00."""
        assert grid.slot_of_day(102) == 3
        assert grid.lands_exactly(102, 12)  # a one-hour class

    def test_a_time_that_does_not(self, grid: Grid) -> None:
        """08:25 is not a ten-minute boundary, and 25 minutes is not a whole number of them."""
        assert not grid.lands_exactly(101, 5)

    def test_a_class_is_rounded_outward_never_inward(self, grid: Grid) -> None:
        """A 25-minute class from 08:25 covers 08:20 to 08:50 on this grid: three slots.

        Rounding inward would hand the solver a room for the last minutes of a class still
        in it, and the timetable would be wrong in a way perfectly consistent with the data
        it was given.
        """
        assert list(grid.covers(101, 5)) == [2, 3, 4]

    def test_a_class_always_covers_at_least_one_slot(self, grid: Grid) -> None:
        """A class shorter than a slot still has to be somewhere."""
        assert len(grid.covers(102, 1)) == 1


class TestWhatIsCarried:
    def test_rooms_keep_their_capacity(self, bet: Instance) -> None:
        plan = mapped(bet)

        assert len(plan.rooms) == 46
        assert plan.rooms[0].name == "Room 1"
        assert plan.rooms[0].capacity == 40

    def test_names_are_traceable_back_to_the_file(self) -> None:
        """ITC rooms and courses have ids and nothing else. Naming them after the id is
        what lets a number in the report be checked by hand against the XML."""
        assert room_name(12) == "Room 12"
        assert course_code(7) == "C7"

    def test_a_course_becomes_a_course_and_an_offering(self, bet: Instance) -> None:
        plan = mapped(bet)

        assert len(plan.courses) == 48
        assert len(plan.offerings) == 48

    def test_the_term_says_where_it_came_from(self, bet: Instance) -> None:
        plan = mapped(bet)

        assert plan.term.name == "bet-sum18"
        assert plan.term.academic_year == "ITC-2019"
        assert plan.institution == "bet-sum18"


class TestRoomClosures:
    def test_a_whole_term_closure_is_carried(self, purdue: Instance) -> None:
        plan = mapped(purdue)

        assert len(plan.closures) == 1
        assert plan.closures[0].slots

    def test_every_carried_slot_is_inside_the_week(self, bet: Instance) -> None:
        plan = mapped(bet)
        week = plan.grid.days * plan.grid.slots_per_day

        for closure in plan.closures:
            assert all(0 <= slot < week for slot in closure.slots)

    def test_a_closure_outside_teaching_hours_is_not_reported_as_a_loss(
        self, bet: Instance
    ) -> None:
        """Two of `bet-sum18`'s 72 windows fall outside 08:00 to 16:50 entirely.

        They forbid nothing, because no class can be scheduled there to forbid. Counting
        them as dropped would inflate the loss with something that costs nothing — the
        report is allowed to come out badly, but not inaccurately in either direction.
        """
        outside = _entry(bet, "room closures outside teaching hours")

        assert outside.fate is Fate.CARRIED
        assert outside.count == 2
        assert len(mapped(bet).closures) == 70

    def test_a_part_term_closure_is_dropped_rather_than_widened(self) -> None:
        """Neither vendored instance has one, so this is built to have one.

        Widening it would block the room in weeks the instance says it is free. That is not
        a lossy import but a wrong one — and it would produce a plausible timetable nobody
        could falsify. `wbg-fal10` has 11 of these, so the rule is not hypothetical.
        """
        instance = read(_with_closure(weeks="110000"))
        plan = mapped(instance)

        assert plan.closures == ()
        dropped = _one(plan.ledger.of(Fate.DROPPED), "room closures")
        assert dropped.count == 1
        assert "some weeks only" in dropped.because

    def test_the_same_closure_every_week_is_carried(self) -> None:
        """The other half of the rule, so the test above cannot pass by dropping everything."""
        plan = mapped(read(_with_closure(weeks="111111")))

        assert len(plan.closures) == 1
        assert plan.closures[0].room == "Room 1"


class TestTheLedger:
    def test_nothing_imports_without_loss(self, bet: Instance, purdue: Instance) -> None:
        """The finding this phase exists to state, and it is not close."""
        assert not mapped(bet).ledger.is_lossless
        assert not mapped(purdue).ledger.is_lossless

    def test_every_class_is_accounted_for(self, bet: Instance) -> None:
        """Not silently absent. A session template must be taught to at least one group,
        and ITC states individual enrolments rather than a programme tree."""
        entry = _entry(bet, "classes")

        assert entry.fate is Fate.DROPPED
        assert entry.count == 127
        assert "group" in entry.because

    def test_students_are_dropped_rather_than_invented(self, purdue: Instance) -> None:
        """D7, applied where it bites hardest. Synthesising groups from enrolments would
        report a fidelity the invention created."""
        entry = _entry(purdue, "students")

        assert entry.fate is Fate.DROPPED
        assert entry.count == 2002

    def test_a_time_option_is_never_counted_as_carried(self, bet: Instance) -> None:
        """The correction that matters most in this file.

        The ledger once counted time options landing on the grid unchanged as *carried*,
        which put over a million things in that column across the set — none of them in any
        project, because every class they belong to is dropped. A report is not allowed to
        claim something arrived when a reader who went looking would not find it.
        """
        plan = mapped(bet)
        carried = {e.what for e in plan.ledger.of(Fate.CARRIED)}

        assert "class time options" not in carried
        assert _entry(bet, "class time options").fate is Fate.DROPPED

    def test_every_time_option_is_dropped_with_its_class(self, bet: Instance) -> None:
        entry = _entry(bet, "class time options")

        assert entry.count == sum(len(k.times) for k in bet.classes)
        assert "with the classes" in entry.because

    def test_how_well_the_grid_holds_them_is_measured_separately(self, bet: Instance) -> None:
        """Still worth knowing, and kept out of the ledger so it cannot be read as arrival.

        If classes ever become representable, this says whether the teaching week would be
        what stopped them.
        """
        plan = mapped(bet)

        assert plan.fit.total == sum(len(k.times) for k in bet.classes)
        assert plan.fit.exact == sum(
            1 for k in bet.classes for t in k.times if plan.grid.lands_exactly(t.start, t.length)
        )
        assert plan.fit.exact == 48

    def test_a_reason_never_names_one_instance(self, bet: Instance, purdue: Instance) -> None:
        """Reasons are summed across 36 instances in the report, so one saying "a term of
        16 weeks" is wrong for the 35 whose term is not 16 weeks. That exact line shipped
        into a generated report before this test existed."""
        for instance in (bet, purdue):
            for entry in mapped(instance).ledger.entries:
                assert str(instance.nr_weeks) not in entry.because
                assert instance.name not in entry.because

    def test_every_distribution_type_is_named_with_its_count(self, bet: Instance) -> None:
        """Eight types in this instance, each its own line. A single 'distributions: 144'
        would hide that the commonest type in the whole benchmark has no counterpart."""
        named = {
            e.what.removeprefix("distribution: "): e.count
            for e in mapped(bet).ledger.of(Fate.DROPPED)
            if e.what.startswith("distribution: ")
        }

        assert named == {
            "SameAttendees": 55,
            "SameRoom": 38,
            "SameDays": 19,
            "WorkDay": 19,
            "SameStart": 5,
            "DifferentDays": 4,
            "NotOverlap": 2,
            "MinGap": 2,
        }
        assert sum(named.values()) == len(bet.distributions)

    def test_a_type_with_a_counterpart_says_why_it_is_still_dropped(self, bet: Instance) -> None:
        """`NotOverlap` maps to `NOT_OVERLAP`, and is dropped anyway — it would refer to
        classes that were themselves dropped. Saying only 'no counterpart' would be wrong,
        and saying nothing would let a reader assume it was carried."""
        entry = _entry(bet, "distribution: NotOverlap")

        assert "NOT_OVERLAP" in entry.because
        assert "themselves dropped" in entry.because

    def test_the_counterpart_table_covers_every_type_in_the_set(
        self, bet: Instance, purdue: Instance
    ) -> None:
        """A type missing from the table would be reported as having no counterpart without
        anyone having checked. Both fixtures together use ten of the nineteen; the sweep
        checks all of them."""
        for instance in (bet, purdue):
            assert {d.name for d in instance.distributions} <= set(COUNTERPARTS)


def _entry(instance: Instance, what: str) -> Entry:
    return _one(mapped(instance).ledger.entries, what)


def _one(entries: tuple[Entry, ...], what: str) -> Entry:
    found = [e for e in entries if e.what == what]
    assert len(found) == 1, f"expected exactly one {what!r} entry, got {len(found)}"
    return found[0]


def _with_closure(*, weeks: str) -> bytes:
    """One room closed on Monday morning, in the weeks given, and one class to set the day.

    Built rather than vendored because the rule under test is about a shape neither vendored
    instance happens to have, and an instance that does have it is 1.4 MiB.
    """
    return (
        '<problem name="closed" nrDays="7" slotsPerDay="288" nrWeeks="6">'
        '<optimization time="1" room="1" distribution="1" student="1"/>'
        '<rooms><room id="1" capacity="30">'
        f'<unavailable days="1000000" start="102" length="12" weeks="{weeks}"/>'
        "</room></rooms>"
        '<courses><course id="1"><config id="1"><subpart id="1">'
        '<class id="1" limit="10"><room id="1" penalty="0"/>'
        '<time days="1000000" start="96" length="48" weeks="111111" penalty="0"/>'
        "</class></subpart></config></course></courses>"
        "<distributions/></problem>"
    ).encode()
