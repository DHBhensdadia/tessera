"""Reading a `.ctt` file exactly as the specification defines it.

The fixture is the **published toy example**, typed from the competition's own technical report
(Di Gaspero, McCollum and Schaerf, §4.1) rather than downloaded — so the parser is checked
against the organisers' own illustration of their format, which is the nearest thing to an
oracle available before any instance is in hand.

That distinction earned itself. A machine summary of the same report gave `RoomCapacity` as
five points per student when the report says one, and reordered all four hard constraints.
Reading the primary source is not ceremony here; it is the difference between a correct parser
and a plausible one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera.importers.cbctt import Instance, MalformedInstanceError, read

TOY = Path(__file__).parent / "fixtures" / "toy.ctt"


@pytest.fixture(scope="module")
def toy() -> Instance:
    return read(TOY)


class TestTheHeader:
    def test_the_shape_of_the_week(self, toy: Instance) -> None:
        assert toy.name == "ToyExample"
        assert (toy.days, toy.periods_per_day) == (5, 4)
        assert toy.periods == 20

    def test_the_counts_match_what_the_header_declares(self, toy: Instance) -> None:
        """The header states each count and the sections carry them. Disagreement means a
        section was mis-parsed, and it is the only self-check the format offers."""
        assert (len(toy.courses), len(toy.rooms)) == (4, 2)
        assert (len(toy.curricula), len(toy.unavailable)) == (2, 8)


class TestTheSections:
    def test_a_course(self, toy: Instance) -> None:
        first = toy.courses[0]

        assert first.id == "SceCosC"
        assert first.teacher == "Ocra"
        assert (first.lectures, first.min_working_days, first.students) == (3, 3, 30)

    def test_a_room(self, toy: Instance) -> None:
        assert [(r.id, r.capacity) for r in toy.rooms] == [("A", 32), ("B", 50)]

    def test_a_curriculum_lists_its_courses(self, toy: Instance) -> None:
        """The thing ITC-2019 did not have. A curriculum is a set of courses taken by the same
        students — a cohort — which is why the barrier that dropped all 52,254 ITC-2019 classes
        is absent here."""
        assert toy.curricula[0].id == "Cur1"
        assert toy.curricula[0].courses == ("SceCosC", "ArcTec", "TecCos")

    def test_an_unavailability_is_a_course_and_a_period(self, toy: Instance) -> None:
        """`TecCos 3 2` means TecCos cannot be taught in the third period of Thursday — days
        and periods count from zero, which the report says explicitly because it is the thing
        everybody gets wrong."""
        assert toy.unavailable[2] == read(TOY).unavailable[2]
        assert (toy.unavailable[2].course, toy.unavailable[2].day) == ("TecCos", 3)
        assert toy.unavailable[2].period == 2

    def test_every_lecture_is_counted(self, toy: Instance) -> None:
        """3 + 3 + 5 + 5. Each becomes one session, so this is how many things a solve places."""
        assert toy.lectures == 16


class TestRefusing:
    def test_a_missing_header_field(self) -> None:
        with pytest.raises(MalformedInstanceError, match="no 'Periods_per_day'"):
            read("Name: x\nCourses: 0\nRooms: 0\nDays: 5\n", name="a stub")

    def test_a_missing_section(self) -> None:
        header = "\n".join(
            f"{k}: {v}"
            for k, v in [
                ("Name", "x"),
                ("Courses", 0),
                ("Rooms", 0),
                ("Days", 5),
                ("Periods_per_day", 4),
                ("Curricula", 0),
                ("Constraints", 0),
            ]
        )
        with pytest.raises(MalformedInstanceError, match="missing the section"):
            read(header + "\n\nCOURSES:\n\nEND.\n", name="a stub")

    def test_a_curriculum_that_miscounts_its_own_courses(self) -> None:
        """The one internal check the format offers, and worth making: a curriculum declaring
        three courses and listing two means a member was lost, and every conflict that member
        was in disappears silently."""
        with pytest.raises(MalformedInstanceError, match="declares 3 courses and lists 2"):
            read(_stub("CURRICULA:\nCur1 3 A B\n"))

    def test_a_course_row_with_the_wrong_number_of_fields(self) -> None:
        with pytest.raises(MalformedInstanceError, match="a course needs five fields"):
            read(_stub("COURSES:\nA Teacher 3 3\n"))

    def test_a_count_that_is_not_a_number(self) -> None:
        with pytest.raises(MalformedInstanceError, match="capacity 'big' is not a number"):
            read(_stub("ROOMS:\nA big\n"))

    def test_a_room_row_with_the_wrong_number_of_fields(self) -> None:
        with pytest.raises(MalformedInstanceError, match="a room needs an id and a capacity"):
            read(_stub("ROOMS:\nA 30 extra\n"))

    def test_an_unavailability_row_with_the_wrong_number_of_fields(self) -> None:
        with pytest.raises(MalformedInstanceError, match="a course, day and period"):
            read(_stub("UNAVAILABILITY_CONSTRAINTS:\nA 2\n"))

    def test_a_curriculum_row_too_short(self) -> None:
        with pytest.raises(MalformedInstanceError, match="an id and a count"):
            read(_stub("CURRICULA:\nCur1\n"))


def _stub(section: str) -> str:
    """The smallest well-formed file, with one section replaced by something wrong."""
    header = "\n".join(
        f"{k}: {v}"
        for k, v in [
            ("Name", "stub"),
            ("Courses", 1),
            ("Rooms", 1),
            ("Days", 5),
            ("Periods_per_day", 4),
            ("Curricula", 1),
            ("Constraints", 1),
        ]
    )
    blocks = {
        "COURSES:": "COURSES:\nA Teacher 1 1 10\n",
        "ROOMS:": "ROOMS:\nA 30\n",
        "CURRICULA:": "CURRICULA:\nCur1 1 A\n",
        "UNAVAILABILITY_CONSTRAINTS:": "UNAVAILABILITY_CONSTRAINTS:\nA 2 0\n",
    }
    heading = (
        section.split("\n")[0] + ":"
        if not section.startswith(tuple(blocks))
        else section.split("\n")[0]
    )
    blocks[heading] = section
    return header + "\n\n" + "\n".join(blocks.values()) + "\nEND.\n"
