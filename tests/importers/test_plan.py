"""Rows into things the project could hold, or into reasons it could not.

The plan is what a dry run reports and what a commit writes, so these tests are the
closest thing this phase has to a specification of its own report.
"""

from __future__ import annotations

import pytest

from tessera.domain import entities as d
from tessera.domain import groups as dg
from tessera.importers.detect import Kind, detect
from tessera.importers.plan import Catalogue, Plan, build
from tessera.importers.sheet import read


@pytest.fixture
def known() -> Catalogue:
    return Catalogue(
        buildings={"Block A": 1, "Block B": 2},
        features={"projector": 1, "computers": 2},
        departments={"Computer Science": 1},
        programs={"BTech CSE": 1},
        groups={"2024 Intake": 1},
    )


def only[T](plan: Plan, expected: type[T]) -> T:
    """The single entity a one-row plan produced, narrowed to what it should be.

    `Prepared.entity` is a union of the four kinds, so asserting the type is how a test
    says which one it is talking about — and catches a builder returning the wrong shape,
    which is otherwise only visible as a confusing attribute error.
    """
    assert plan.rows_ready == 1
    entity = plan.ready[0].entity
    assert isinstance(entity, expected)
    return entity


def plan_for(csv: bytes, known: Catalogue, kind: Kind | None = None) -> Plan:
    sheet = read(csv, "sheet.csv")
    found = detect(sheet.headers)
    chosen = kind or found.kind
    assert chosen is not None
    return build(sheet, chosen, found.mapping, known)


class TestWhatGetsThrough:
    def test_a_clean_room_sheet(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats,Block,Equipment\nLH-201,150,Block A,projector\n", known)

        room = only(plan, d.Room)
        assert room.name == "LH-201"
        assert room.capacity == 150
        assert room.building_id == 1
        assert room.features == frozenset({1})

    def test_several_features_in_one_cell(self, known: Catalogue) -> None:
        """`projector, computers` in a single cell is how most people write it."""
        plan = plan_for(b'Room,Seats,Equipment\nLab 1,45,"projector, computers"\n', known)

        assert only(plan, d.Room).features == frozenset({1, 2})

    def test_names_match_regardless_of_spacing_and_case(self, known: Catalogue) -> None:
        """Nobody types `Block A` the same way twice across two hundred rows."""
        plan = plan_for(b"Room,Seats,Block\nLH-201,150,  block   a \n", known)

        assert only(plan, d.Room).building_id == 1

    def test_a_row_carries_the_line_it_came_from(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats\nLH-201,150\nLH-202,80\n", known)

        assert [prepared.row for prepared in plan.ready] == [2, 3]

    def test_blank_lines_are_not_rows(self, known: Catalogue) -> None:
        """A gap between blocks of a spreadsheet is formatting, not a missing record."""
        plan = plan_for(b"Room,Seats\nLH-201,150\n\n\nLH-204,60\n", known)

        assert plan.rows_total == 2
        assert plan.rows_ready == 2


class TestWhatGetsReported:
    def test_a_word_where_a_number_belongs_quotes_the_word(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats\nLH-202,forty\n", known)

        assert plan.rows_ready == 0
        assert "'forty'" in plan.problems[0].message
        assert plan.problems[0].row == 2

    def test_an_unknown_reference_names_it(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats,Block\nLH-201,150,Block Q\n", known)

        assert "No building called 'Block Q'" in plan.problems[0].message

    def test_a_near_miss_suggests_the_real_thing(self, known: Catalogue) -> None:
        """P5's own example: "row 14: room LH-201 references unknown feature
        'projecter'". The useful half is the last word."""
        plan = plan_for(b"Room,Seats,Equipment\nLH-201,150,projecter\n", known)

        assert plan.problems[0].suggestion == "projector"

    def test_the_suggestion_is_never_applied(self, known: Catalogue) -> None:
        """An importer that silently corrects `projecter` will one day silently merge
        two genuinely different rooms, and nobody will know which import did it."""
        plan = plan_for(b"Room,Seats,Equipment\nLH-201,150,projecter\n", known)

        assert plan.rows_ready == 0

    def test_something_unrelated_gets_no_suggestion(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats,Equipment\nLH-201,150,swimming pool\n", known)

        assert plan.problems[0].suggestion == ""

    def test_a_missing_name_is_reported_against_its_column(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats\n,150\n", known)

        assert plan.problems[0].column == "name"

    def test_every_problem_in_a_row_is_reported_at_once(self, known: Catalogue) -> None:
        """Fixing a spreadsheet one error per upload is how a person gives up and types
        the data in by hand instead."""
        plan = plan_for(b"Room,Seats,Block,Equipment\n,forty,Block Q,projecter\n", known)

        assert {problem.column for problem in plan.problems} == {
            "name",
            "capacity",
            "building",
            "features",
        }

    def test_a_duplicated_header_is_reported_against_the_header_row(self, known: Catalogue) -> None:
        plan = plan_for(b"Room,Seats,Room\nLH-201,150,Other\n", known)

        header_problems = [p for p in plan.problems if p.row == 1]
        assert header_problems and "more than once" in header_problems[0].message


class TestTheDomainDoesTheValidating:
    def test_a_negative_capacity_is_refused_by_the_room_itself(self, known: Catalogue) -> None:
        """Not a rule the importer restates. `Room.capacity` is `ge=0`, and a second copy
        of that here would be a second copy to keep in step."""
        plan = plan_for(b"Room,Seats\nLH-201,-5\n", known)

        assert plan.rows_ready == 0
        assert "greater than or equal to 0" in plan.problems[0].message

    def test_the_message_is_the_domains_own_words(self, known: Catalogue) -> None:
        """Pydantic's full text is four lines of machine detail. What reaches the report
        is the sentence a person can act on."""
        plan = plan_for(b"Room,Seats\nLH-201,-5\n", known)

        assert "type=greater_than_equal" not in plan.problems[0].message


class TestTheOtherKinds:
    def test_instructors(self, known: Catalogue) -> None:
        plan = plan_for(
            b"Instructor,Email,Dept\nProf. Sharma,ps@example.edu,Computer Science\n", known
        )

        assert only(plan, d.Instructor).department_id == 1

    def test_courses(self, known: Catalogue) -> None:
        plan = plan_for(
            b"Course Code,Title,Credits,Dept\nCS301,Operating Systems,4,Computer Science\n",
            known,
        )

        course = only(plan, d.Course)
        assert course.code == "CS301"
        assert course.credits == 4

    def test_groups_resolve_their_parent_by_name(self, known: Catalogue) -> None:
        plan = plan_for(b"Group,Students,Parent Group\nA1,40,2024 Intake\n", known)

        assert only(plan, dg.StudentGroup).parent_id == 1

    def test_a_parent_that_is_not_there_yet_is_reported(self, known: Catalogue) -> None:
        """Groups arrive in one file and a parent is often a row above. The plan reports
        against the project as it stands; ordering is the applier's job in part 2."""
        plan = plan_for(b"Group,Students,Parent Group\nA1,40,2025 Intake\n", known)

        assert "No group called '2025 Intake'" in plan.problems[0].message
        assert plan.problems[0].suggestion == "2024 Intake"
