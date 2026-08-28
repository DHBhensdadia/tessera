"""Reading a competition instance exactly as it is written.

Two real instances are vendored beside this file, not invented ones. An invented fixture
tests the parser against my reading of the specification, and my reading of the specification
is the thing most likely to be wrong — these files were written by the organisers and solved
by everyone in the competition, so where they disagree with me, they are right.

Two, because no single small instance exercises everything. `bet-sum18` has weeks that vary,
classes that need no room, parent classes and eight distribution types but no students and no
travel times; `pu-cs-fal07` has two thousand students and travel times but no roomless
classes. Between them every branch in `format.py` is taken.

Not `wbg-fal10`, which plan 4.0 named: it has **no** varied weeks and **no** travel times, so
it cannot fail the way that matters. Part 1 exists because a mis-read week mask makes every
number in the fidelity report wrong and silent about it; a fixture that never varies its weeks
would have let exactly that through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera.importers.itc import Instance, MalformedInstanceError, read

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def bet() -> Instance:
    """Brno, summer 2018. 127 classes, six weeks, no students."""
    return read(FIXTURES / "bet-sum18.xml")


@pytest.fixture(scope="module")
def purdue() -> Instance:
    """Purdue computer science, autumn 2007. 174 classes and 2,002 students."""
    return read(FIXTURES / "pu-cs-fal07.xml")


class TestTheHeader:
    def test_the_shape_of_the_week(self, bet: Instance) -> None:
        assert bet.name == "bet-sum18"
        assert (bet.nr_days, bet.slots_per_day, bet.nr_weeks) == (7, 288, 6)

    def test_the_objective_weights(self, bet: Instance) -> None:
        """Four weights, and they are not all one — a parser that read them positionally
        from the wrong attributes would still produce four plausible numbers."""
        assert (bet.optimization.time, bet.optimization.room) == (1, 1)
        assert (bet.optimization.distribution, bet.optimization.student) == (10, 10)

    def test_the_counts(self, bet: Instance, purdue: Instance) -> None:
        assert (len(bet.rooms), len(bet.courses), len(bet.classes)) == (46, 48, 127)
        assert (len(bet.distributions), len(bet.students)) == (144, 0)
        assert (len(purdue.rooms), len(purdue.courses), len(purdue.classes)) == (13, 44, 174)
        assert (len(purdue.distributions), len(purdue.students)) == (102, 2002)


class TestAClass:
    def test_what_the_first_one_says(self, bet: Instance) -> None:
        first = bet.classes[0]

        assert (first.id, first.limit) == (1, 35)
        assert first.parent is None
        assert first.needs_room
        assert (len(first.rooms), len(first.times)) == (15, 1)

    def test_a_room_option_carries_its_penalty(self, bet: Instance) -> None:
        """Penalty 1, not 0. Rooms are ranked, and a parser that dropped the penalty would
        make every room equally good and the room objective meaningless."""
        assert bet.classes[0].rooms[0].room == 8
        assert bet.classes[0].rooms[0].penalty == 1

    def test_a_time_option_is_read_whole(self, bet: Instance) -> None:
        only = bet.classes[0].times[0]

        assert only.days == "1111100"  # weekdays
        assert (only.start, only.length) == (96, 15)  # 08:00, seventy-five minutes
        assert only.weeks == "111111"
        assert only.penalty == 0

    def test_a_class_may_have_a_parent(self, bet: Instance) -> None:
        """A student taking 12 must also take 11. Thirty-seven of the 127 say so."""
        assert next(k for k in bet.classes if k.id == 12).parent == 11
        assert sum(1 for k in bet.classes if k.parent is not None) == 37

    def test_a_class_may_need_no_room(self, bet: Instance) -> None:
        """`room="false"`, which is not the same as offering no room options — it means the
        class is taught somewhere the timetable does not schedule."""
        assert not next(k for k in bet.classes if k.id == 88).needs_room
        assert sum(1 for k in bet.classes if not k.needs_room) == 6

    def test_every_class_offers_at_least_one_time(self, bet: Instance, purdue: Instance) -> None:
        """True of all 52,254 classes in the competition set, and load-bearing: a class with
        no time option cannot be scheduled at all, so anything reading an empty list as a
        free choice would be inventing options nobody offered."""
        assert all(k.times for k in bet.classes)
        assert all(k.times for k in purdue.classes)


class TestTheWeekDimension:
    """The thing Tessera does not have, and therefore the thing to read most carefully."""

    def test_weeks_that_vary(self, bet: Instance) -> None:
        varied = [t for k in bet.classes for t in k.times if not t.is_every_week]

        assert len(varied) == 22
        assert any(t.weeks == "111000" for t in varied)  # the first half of term only

    def test_an_instance_knows_whether_it_needs_more_than_one_week(self, bet: Instance) -> None:
        assert bet.needs_multiple_weeks

    def test_a_mask_is_kept_as_written(self, purdue: Instance) -> None:
        """Not decoded into a set of week numbers. The report has to quote these back, and a
        round trip through a set is a chance to lose the length."""
        first = purdue.classes[0].times[0]

        assert first.weeks == "1" * 15
        assert first.is_every_week

    def test_a_mask_of_the_wrong_length_is_refused(self) -> None:
        """The failure this whole file is arranged around. A `weeks` string one character
        short shifts every week it names, and the instance stays well-formed XML — so the
        length is checked against what the header declared rather than trusted."""
        with pytest.raises(MalformedInstanceError, match="weeks='111' is not 6 binary digits"):
            read(_instance(weeks="111"))

    def test_a_mask_that_is_not_binary_is_refused(self) -> None:
        with pytest.raises(MalformedInstanceError, match="not 7 binary digits"):
            read(_instance(days="1112100"))


class TestARoom:
    def test_travel_times(self, purdue: Instance) -> None:
        """Twelve slots — an hour — between two rooms. Tessera has buildings and a soft
        preference against moving between them, which is qualitative where this is a number,
        and that difference is `fidelity.py`'s to report."""
        first = next(r for r in purdue.rooms if r.travel)

        assert (first.id, first.capacity) == (1, 61)
        assert first.travel[0].room == 2
        assert first.travel[0].value == 12
        assert len(first.travel) == 10

    def test_unavailability(self, bet: Instance) -> None:
        """A room closed for part of the week — Monday, from 07:30, for eleven hours."""
        closed = next(r for r in bet.rooms if r.unavailable)
        window = closed.unavailable[0]

        assert closed.id == 1
        assert window.days == "1000000"
        assert (window.start, window.length) == (90, 132)
        assert window.weeks == "111111"
        assert sum(len(r.unavailable) for r in bet.rooms) == 72


class TestADistribution:
    def test_a_hard_one(self, bet: Instance) -> None:
        same = next(d for d in bet.distributions if d.type == "SameAttendees")

        assert same.required
        assert same.penalty is None
        assert same.classes == (2, 7)

    def test_a_soft_one_carries_a_penalty_instead(self, bet: Instance) -> None:
        """Never both. The format says hard-or-soft by which attribute is present, so a
        parser inventing a default weight for a required constraint would be adding a number
        the file does not contain."""
        soft = next(d for d in bet.distributions if not d.required)

        assert soft.penalty == 4
        assert sum(1 for d in bet.distributions if not d.required) == 34

    def test_parameters_are_split_from_the_name(self, bet: Instance) -> None:
        """`WorkDay(32)` is a type and a number, and the number is the constraint. Kept as
        both: the written form for the report to quote, the parts for anything acting on it."""
        workday = next(d for d in bet.distributions if d.name == "WorkDay")

        assert workday.type == "WorkDay(32)"
        assert workday.parameters == (32,)

    def test_an_unparameterised_type_has_no_parameters(self, bet: Instance) -> None:
        assert next(d for d in bet.distributions if d.name == "SameStart").parameters == ()

    def test_every_type_in_the_fixture(self, bet: Instance) -> None:
        assert {d.name for d in bet.distributions} == {
            "DifferentDays",
            "MinGap",
            "NotOverlap",
            "SameAttendees",
            "SameDays",
            "SameRoom",
            "SameStart",
            "WorkDay",
        }

    def test_two_parameters(self) -> None:
        """`MaxBlock(120,30)` — the competition set has six two-parameter types."""
        found = read(
            _instance(
                distribution='<distribution type="MaxBlock(120,30)" required="true">'
                '<class id="1"/><class id="1"/></distribution>'
            )
        )

        assert found.distributions[0].parameters == (120, 30)

    def test_neither_required_nor_penalty_is_refused(self) -> None:
        with pytest.raises(MalformedInstanceError, match="neither required nor penalty"):
            read(
                _instance(
                    distribution='<distribution type="SameRoom"><class id="1"/></distribution>'
                )
            )

    def test_both_required_and_penalty_is_refused(self) -> None:
        with pytest.raises(MalformedInstanceError, match="both required and penalty"):
            read(
                _instance(
                    distribution='<distribution type="SameRoom" required="true" penalty="4">'
                    '<class id="1"/></distribution>'
                )
            )


class TestAStudent:
    def test_the_courses_they_want(self, purdue: Instance) -> None:
        assert purdue.students[0].id == 1
        assert purdue.students[0].courses == (4,)

    def test_an_instance_may_have_none(self, bet: Instance) -> None:
        """Six of the 36 published instances have no students at all, so an absent
        `<students>` element is a shape to read rather than an error."""
        assert bet.students == ()


class TestRefusing:
    """Every unexpected thing raises, because the alternative is a wrong number in a report
    nobody can falsify. This is the one module where a sensible default is the bug."""

    def test_something_that_is_not_xml(self) -> None:
        with pytest.raises(MalformedInstanceError, match="not well-formed XML"):
            read(b"course code, room\nCS101, A1\n", name="a spreadsheet")

    def test_xml_that_is_not_an_instance(self) -> None:
        with pytest.raises(MalformedInstanceError, match="<solution> at its root"):
            read(b'<solution name="x"/>', name="a solution file")

    def test_a_missing_attribute(self) -> None:
        with pytest.raises(MalformedInstanceError, match="<problem> has no 'nrWeeks'"):
            read(b'<problem name="x" nrDays="7" slotsPerDay="288"/>')

    def test_an_attribute_that_is_not_a_number(self) -> None:
        with pytest.raises(MalformedInstanceError, match="capacity='big' is not a number"):
            read(_instance(capacity="big"))

    def test_an_instance_with_no_objective(self) -> None:
        """Every published instance weights all four terms. One without them could still be
        parsed — and the fidelity report would then quote an objective nobody wrote."""
        with pytest.raises(MalformedInstanceError, match="no <optimization> weights"):
            read(b'<problem name="x" nrDays="7" slotsPerDay="288" nrWeeks="6"/>')

    def test_a_distribution_type_in_a_shape_never_seen(self) -> None:
        """The competition uses `Name` or `Name(1,2)`. Anything else would have to be guessed
        at, and a guessed constraint type is a wrong line in the report."""
        with pytest.raises(MalformedInstanceError, match="not a form this parser reads"):
            read(
                _instance(
                    distribution='<distribution type="Max-Block[3]" required="true">'
                    '<class id="1"/></distribution>'
                )
            )

    def test_a_room_spelling_that_has_never_been_seen(self) -> None:
        """`room="false"` is the only value the competition set uses. `room="true"` would be
        readable, and reading it would mean guessing that the organisers meant what I assume."""
        with pytest.raises(MalformedInstanceError, match="room='true'; only 'false' or absent"):
            read(_instance(room='room="true"'))


_SAME_ROOM = '<distribution type="SameRoom" required="true"><class id="1"/></distribution>'


def _instance(
    *,
    days: str = "1010100",
    weeks: str = "111111",
    capacity: str = "30",
    room: str = "",
    distribution: str = _SAME_ROOM,
) -> bytes:
    """The smallest well-formed instance, with one thing at a time made wrong.

    Inline rather than vendored: these are files the organisers never wrote, and keeping them
    as strings makes it obvious which single attribute each test is about.
    """
    return (
        '<problem name="tiny" nrDays="7" slotsPerDay="288" nrWeeks="6">'
        '<optimization time="1" room="1" distribution="1" student="1"/>'
        f'<rooms><room id="1" capacity="{capacity}"/></rooms>'
        '<courses><course id="1"><config id="1"><subpart id="1">'
        f'<class id="1" limit="10" {room}>'
        f'<room id="1" penalty="0"/>'
        f'<time days="{days}" start="96" length="12" weeks="{weeks}" penalty="0"/>'
        "</class></subpart></config></course></courses>"
        f"<distributions>{distribution}</distributions>"
        "</problem>"
    ).encode()
