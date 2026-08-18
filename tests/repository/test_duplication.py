"""Rolling a term forward.

The exit test of Phase 2.9, and the phase's whole justification: the first semester costs
a day of data entry and every one after it should cost an hour. That is only true if what
carries over carries over completely — so most of these tests are about the things a
duplicate would be easiest to lose quietly.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain.constraints import ConstraintKind, ConstraintTarget, TargetKind
from tessera.repository import calendar as calendar_repo
from tessera.repository import constraints as constraints_repo
from tessera.repository import duplication, expansion
from tessera.repository import models as m
from tessera.repository import people as people_repo
from tessera.repository import sessions as sessions_repo
from tessera.repository.duplication import Carried
from tessera.repository.errors import NotFoundError, RuleViolationError


@pytest.fixture
def autumn(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> m.Term:
    """A term made the way the application makes one, so it has its default preferences."""
    created = calendar_repo.create_term(
        db,
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name="Autumn",
    )
    db.commit()
    row = db.get(m.Term, int(created.id or 0))
    assert row is not None
    return row


@pytest.fixture
def shah(db: DbSession) -> m.Instructor:
    row = m.Instructor(name="Prof. Shah")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def batch(db: DbSession) -> m.StudentGroup:
    row = m.StudentGroup(name="CSE5-A1", size=30)
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def taught(db: DbSession, autumn: m.Term, batch: m.StudentGroup, shah: m.Instructor) -> m.Offering:
    """One course offered, with a weekly pattern of two lectures."""
    course = m.Course(code="CS301", name="Operating Systems")
    db.add(course)
    db.commit()

    offering = calendar_repo.create_offering(db, term_id=autumn.id, course_id=int(course.id))
    db.commit()
    sessions_repo.create_template(
        db,
        offering_id=int(offering.id or 0),
        kind=d.SessionKind.LECTURE,
        duration_slots=2,
        per_week=2,
        attendee_ids=[int(batch.id)],
        instructor_ids=[int(shah.id)],
    )
    db.commit()
    # Templates are a weekly *pattern*; the sessions come from expanding it. Nothing
    # expands implicitly (2.4), so a fixture that skipped this would duplicate a term
    # that had no sessions and prove nothing.
    expansion.expand(db, int(offering.id or 0))
    db.commit()

    row = db.get(m.Offering, int(offering.id or 0))
    assert row is not None
    return row


def roll_forward(db: DbSession, term: m.Term, **flags: bool) -> duplication.Receipt:
    receipt = duplication.duplicate_term(
        db, term.id, name="Spring", academic_year="2026-27", **flags
    )
    db.commit()
    return receipt


class TestTheTuningSurvives:
    """D5, and the trap 2.8 set.

    `create_term` seeds seven default preferences. A duplicate that goes through that path
    and stops there would look like it worked and would have thrown away every weight the
    user set — which is the one thing duplication exists to preserve.
    """

    def test_a_retuned_weight_comes_across(self, db: DbSession, autumn: m.Term) -> None:
        original = constraints_repo.list_constraints(
            db, autumn.id, kind=ConstraintKind.MINIMISE_GROUP_GAPS
        )[0]
        constraints_repo.update_constraint(db, int(original.id or 0), changes={"weight": 19})
        db.commit()

        receipt = roll_forward(db, autumn)

        carried = constraints_repo.list_constraints(
            db, int(receipt.term.id or 0), kind=ConstraintKind.MINIMISE_GROUP_GAPS
        )[0]
        assert carried.weight == 19, "the tuning was re-seeded rather than carried"

    def test_the_new_term_does_not_also_get_the_defaults(
        self, db: DbSession, autumn: m.Term
    ) -> None:
        """Two of each, with different weights, and no way to tell which the solver read."""
        receipt = roll_forward(db, autumn)

        kinds = [c.kind for c in constraints_repo.list_constraints(db, int(receipt.term.id or 0))]
        assert len(kinds) == len(set(kinds)) == 7

    def test_a_disabled_preference_stays_disabled(self, db: DbSession, autumn: m.Term) -> None:
        original = constraints_repo.list_constraints(
            db, autumn.id, kind=ConstraintKind.BALANCE_DAILY_LOAD
        )[0]
        constraints_repo.update_constraint(db, int(original.id or 0), changes={"enabled": False})
        db.commit()

        receipt = roll_forward(db, autumn)

        carried = constraints_repo.list_constraints(
            db, int(receipt.term.id or 0), kind=ConstraintKind.BALANCE_DAILY_LOAD
        )[0]
        assert not carried.enabled

    def test_a_rule_about_a_person_comes_across(
        self, db: DbSession, autumn: m.Term, shah: m.Instructor
    ) -> None:
        constraints_repo.create_constraint(
            db,
            autumn.id,
            kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS,
            targets=[ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=int(shah.id))],
            params={"slots": 3},
            is_hard=True,
        )
        db.commit()

        receipt = roll_forward(db, autumn)

        carried = constraints_repo.list_constraints(
            db, int(receipt.term.id or 0), kind=ConstraintKind.LIMIT_CONSECUTIVE_SLOTS
        )[0]
        assert carried.targets == {ConstraintTarget(kind=TargetKind.INSTRUCTOR, id=int(shah.id))}
        assert carried.is_hard

    def test_a_rule_about_last_term_s_sessions_is_dropped(
        self, db: DbSession, autumn: m.Term, taught: m.Offering, batch: m.StudentGroup
    ) -> None:
        """Those sessions belong to the term being copied from.

        Carrying the target ids across would point the new rule at rows in the old term —
        a constraint that silently constrains nothing, or worse, something unrelated.
        """
        old_sessions = sessions_repo.list_sessions(db, term_id=autumn.id)
        constraints_repo.create_constraint(
            db,
            autumn.id,
            kind=ConstraintKind.NOT_OVERLAP,
            targets=[
                ConstraintTarget(kind=TargetKind.SESSION, id=int(s.id or 0)) for s in old_sessions
            ],
        )
        db.commit()

        receipt = roll_forward(db, autumn)

        assert (
            constraints_repo.list_constraints(
                db, int(receipt.term.id or 0), kind=ConstraintKind.NOT_OVERLAP
            )
            == []
        ), "a rule that is meaningless without targets should be skipped, not emptied"


class TestAvailability:
    def test_the_week_someone_cannot_teach_comes_across(
        self, db: DbSession, autumn: m.Term, shah: m.Instructor
    ) -> None:
        people_repo.block_slots(
            db, autumn.id, kind="instructor", subject_id=int(shah.id), slots=[4, 5]
        )
        db.commit()

        receipt = roll_forward(db, autumn)

        assert people_repo.blocked_slots(
            db, int(receipt.term.id or 0), instructor_id=int(shah.id)
        ) == frozenset({4, 5})

    def test_would_rather_not_does_not_become_cannot(
        self, db: DbSession, autumn: m.Term, shah: m.Instructor
    ) -> None:
        """A preference arriving as a prohibition is a rule nobody wrote."""
        people_repo.block_slots(
            db,
            autumn.id,
            kind="instructor",
            subject_id=int(shah.id),
            slots=[7],
            is_hard=False,
            weight=5,
        )
        db.commit()

        receipt = roll_forward(db, autumn)
        target = int(receipt.term.id or 0)

        assert people_repo.blocked_slots(db, target, instructor_id=int(shah.id)) == frozenset()
        assert people_repo.discouraged_slots(db, target, instructor_id=int(shah.id)) == {7: 5}

    def test_room_availability_can_be_left_behind(
        self, db: DbSession, autumn: m.Term, shah: m.Instructor
    ) -> None:
        room = m.Room(name="Lab 1", capacity=40)
        db.add(room)
        db.commit()
        people_repo.block_slots(db, autumn.id, kind="room", subject_id=int(room.id), slots=[2])
        people_repo.block_slots(
            db, autumn.id, kind="instructor", subject_id=int(shah.id), slots=[2]
        )
        db.commit()

        receipt = roll_forward(db, autumn, copy_rooms=False)
        target = int(receipt.term.id or 0)

        assert people_repo.blocked_slots(db, target, instructor_id=int(shah.id)) == frozenset({2})
        assert (
            db.query(m.Unavailability).filter_by(term_id=target, room_id=int(room.id)).count() == 0
        )


class TestWhatIsTaught:
    def test_offerings_and_their_patterns_come_across(
        self, db: DbSession, autumn: m.Term, taught: m.Offering
    ) -> None:
        receipt = roll_forward(db, autumn)
        target = int(receipt.term.id or 0)

        offerings = calendar_repo.list_offerings(db, term_id=target)
        assert len(offerings) == 1
        templates = sessions_repo.list_templates(db, offering_id=int(offerings[0].id or 0))
        assert [t.per_week for t in templates] == [2]

    def test_the_new_term_has_its_own_sessions(
        self, db: DbSession, autumn: m.Term, taught: m.Offering
    ) -> None:
        """Expanded, not copied — so they are new rows against the new templates."""
        receipt = roll_forward(db, autumn)
        target = int(receipt.term.id or 0)

        old = {int(s.id or 0) for s in sessions_repo.list_sessions(db, term_id=autumn.id)}
        new = {int(s.id or 0) for s in sessions_repo.list_sessions(db, term_id=target)}

        assert len(new) == len(old) == 2
        assert old.isdisjoint(new)

    def test_a_lab_split_two_ways_still_splits(
        self, db: DbSession, autumn: m.Term, taught: m.Offering, batch: m.StudentGroup
    ) -> None:
        second = m.StudentGroup(name="CSE5-A2", size=30)
        db.add(second)
        db.commit()
        sessions_repo.create_template(
            db,
            offering_id=int(taught.id),
            kind=d.SessionKind.LAB,
            duration_slots=2,
            per_week=1,
            attendee_ids=[int(batch.id), int(second.id)],
            split_per_attendee=True,
        )
        expansion.expand(db, int(taught.id))
        db.commit()

        receipt = roll_forward(db, autumn)
        target = int(receipt.term.id or 0)

        labs = [s for s in sessions_repo.list_sessions(db, term_id=target) if s.kind == "lab"]
        assert len(labs) == 2

    def test_the_week_pattern_of_a_fortnightly_lab_comes_across(
        self, db: DbSession, autumn: m.Term, taught: m.Offering, batch: m.StudentGroup
    ) -> None:
        created = sessions_repo.create_template(
            db,
            offering_id=int(taught.id),
            kind=d.SessionKind.LAB,
            duration_slots=2,
            per_week=1,
            attendee_ids=[int(batch.id)],
        )
        # Set on the row rather than through `create_template`, which has no parameter
        # for it — the "stored but with no way in" gap logged in BACKLOG after 2.7b, and
        # explicitly not 2.9's to close. What is under test here is whether duplication
        # carries the pattern, and that does not depend on how it was set.
        row = db.get(m.SessionTemplate, int(created.id or 0))
        assert row is not None
        row.week_pattern = d.WeekPattern.ODD_WEEKS.value
        db.commit()

        receipt = roll_forward(db, autumn)
        offerings = calendar_repo.list_offerings(db, term_id=int(receipt.term.id or 0))
        templates = sessions_repo.list_templates(db, offering_id=int(offerings[0].id or 0))

        assert {t.week_pattern for t in templates} == {
            d.WeekPattern.EVERY_WEEK,
            d.WeekPattern.ODD_WEEKS,
        }

    def test_offerings_can_be_left_behind(
        self, db: DbSession, autumn: m.Term, taught: m.Offering
    ) -> None:
        receipt = roll_forward(db, autumn, copy_offerings=False)

        assert calendar_repo.list_offerings(db, term_id=int(receipt.term.id or 0)) == []


class TestAssignmentsAreCleared:
    def test_a_placed_timetable_does_not_come_across(
        self, db: DbSession, autumn: m.Term, taught: m.Offering
    ) -> None:
        """The exit test's second half, true by construction rather than by deletion."""
        timetable = m.Timetable(term_id=autumn.id, name="Draft")
        db.add(timetable)
        db.commit()
        room = m.Room(name="LH-1", capacity=60)
        db.add(room)
        db.commit()
        placed = sessions_repo.list_sessions(db, term_id=autumn.id)[0]
        db.add(
            m.Assignment(
                timetable_id=timetable.id,
                term_id=autumn.id,
                session_id=int(placed.id or 0),
                room_id=int(room.id),
                start_slot=0,
            )
        )
        db.commit()

        receipt = roll_forward(db, autumn)
        target = int(receipt.term.id or 0)

        assert db.query(m.Timetable).filter_by(term_id=target).count() == 0
        assert db.query(m.Assignment).filter_by(term_id=target).count() == 0

    def test_assignments_without_offerings_is_refused(self, db: DbSession, autumn: m.Term) -> None:
        """Asking to place sessions that will not exist."""
        with pytest.raises(RuleViolationError, match="without the offerings"):
            duplication.duplicate_term(
                db,
                autumn.id,
                name="Spring",
                academic_year="2026-27",
                copy_offerings=False,
                copy_assignments=True,
            )


class TestTheOriginalIsUntouched:
    def test_every_table_is_unchanged(
        self, db: DbSession, autumn: m.Term, taught: m.Offering, shah: m.Instructor
    ) -> None:
        """The failure that would be worst and least visible.

        A duplicate that reparents rather than copies looks correct in the new term and
        silently empties the old one — which nobody checks, because they were looking at
        the new term.
        """
        people_repo.block_slots(
            db, autumn.id, kind="instructor", subject_id=int(shah.id), slots=[4]
        )
        db.commit()

        before = _snapshot(db, autumn.id)
        roll_forward(db, autumn)
        assert _snapshot(db, autumn.id) == before


class TestTheReceipt:
    def test_things_above_a_term_are_reported_as_shared(
        self, db: DbSession, autumn: m.Term
    ) -> None:
        """They cannot be copied and cannot be withheld, so neither word would be honest."""
        receipt = roll_forward(db, autumn)

        for name in duplication.SHARED_BY_NATURE:
            assert receipt.items[name] is Carried.SHARED

    def test_unticking_something_shared_is_reported_as_skipped(
        self, db: DbSession, autumn: m.Term
    ) -> None:
        receipt = roll_forward(db, autumn, copy_courses=False)
        assert receipt.items["courses"] is Carried.SKIPPED

    def test_what_was_copied_is_counted(
        self, db: DbSession, autumn: m.Term, taught: m.Offering
    ) -> None:
        receipt = roll_forward(db, autumn)

        assert receipt.items["offerings"] is Carried.COPIED
        assert receipt.counts["offerings"] == 1
        assert receipt.counts["sessions"] == 2
        assert receipt.counts["constraints"] == 7

    def test_assignments_are_always_reported_as_skipped(
        self, db: DbSession, autumn: m.Term
    ) -> None:
        assert roll_forward(db, autumn).items["assignments"] is Carried.SKIPPED


class TestRefusals:
    def test_duplicating_into_a_name_that_already_exists(
        self, db: DbSession, autumn: m.Term
    ) -> None:
        """The commonest mistake: duplicating Autumn into Autumn."""
        with pytest.raises(Exception, match=r"already exists|Autumn"):
            duplication.duplicate_term(db, autumn.id, name="Autumn", academic_year="2026-27")

    def test_duplicating_a_term_that_does_not_exist(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            duplication.duplicate_term(db, 999, name="Spring", academic_year="2026-27")


def _snapshot(db: DbSession, term_id: int) -> dict[str, object]:
    """Everything term-scoped, as values rather than rows, for an equality check."""
    offerings = calendar_repo.list_offerings(db, term_id=term_id)
    return {
        "offerings": sorted(int(o.course_id or 0) for o in offerings),
        "templates": sorted(
            (t.kind, t.per_week, t.duration_slots)
            for o in offerings
            for t in sessions_repo.list_templates(db, offering_id=int(o.id or 0))
        ),
        "sessions": sorted(
            (s.kind, s.occurrence) for s in sessions_repo.list_sessions(db, term_id=term_id)
        ),
        "constraints": sorted(
            (c.kind.value, c.weight, c.enabled)
            for c in constraints_repo.list_constraints(db, term_id)
        ),
        "unavailability": sorted(
            (u.instructor_id, u.room_id, u.slot, u.is_hard, u.weight)
            for u in people_repo.list_unavailability(db, term_id)
        ),
    }


def test_the_exit_test(
    db: DbSession, autumn: m.Term, taught: m.Offering, shah: m.Instructor, batch: m.StudentGroup
) -> None:
    """Phase 2.9's exit test, in one place.

    *A term duplicates into the next semester carrying its offerings, its weekly patterns,
    its availability and its tuned constraint weights; the new term has its own sessions
    and no assignments; the original is untouched.*
    """
    tuned = constraints_repo.list_constraints(
        db, autumn.id, kind=ConstraintKind.MINIMISE_GROUP_GAPS
    )[0]
    constraints_repo.update_constraint(db, int(tuned.id or 0), changes={"weight": 19})
    people_repo.block_slots(
        db, autumn.id, kind="instructor", subject_id=int(shah.id), slots=[4], is_hard=False
    )
    db.commit()
    before = _snapshot(db, autumn.id)

    receipt = roll_forward(db, autumn)
    target = int(receipt.term.id or 0)

    assert len(calendar_repo.list_offerings(db, term_id=target)) == 1
    assert len(sessions_repo.list_sessions(db, term_id=target)) == 2
    assert (
        constraints_repo.list_constraints(db, target, kind=ConstraintKind.MINIMISE_GROUP_GAPS)[
            0
        ].weight
        == 19
    )
    assert people_repo.discouraged_slots(db, target, instructor_id=int(shah.id)) == {4: 1}
    assert db.query(m.Assignment).filter_by(term_id=target).count() == 0
    assert _snapshot(db, autumn.id) == before
