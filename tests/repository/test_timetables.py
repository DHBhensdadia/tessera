"""Timetables: the first thing in this project that a solve produces.

The tables were written in the first migration and nothing has ever stored a row in them —
Decision #94 moved these routes to 4.7 because it is *"the first phase in which a timetable can
exist at all"*. So these are the tests for a module with no predecessor, and the guards that
matter are the two the schema cannot state on its own: a lineage that crosses terms, and a
placement naming somebody else's session.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain.ids import RoomId, SessionId
from tessera.domain.timetable import Assignment, TimetableStatus
from tessera.repository import calendar as calendar_repo
from tessera.repository import models as m
from tessera.repository import timetables as repo
from tessera.repository.errors import (
    ConflictError,
    InvalidReferenceError,
    NotFoundError,
    RuleViolationError,
)
from tests.repository.authored import Term, term_with_sessions


@pytest.fixture
def autumn(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> Term:
    return term_with_sessions(db, institution, grid)


def placed(term: Term, *, pinned: int = 0) -> list[Assignment]:
    return [
        Assignment(
            session_id=SessionId(session_id),
            start_slot=index * 2,
            room_id=RoomId(term.room_ids[0]),
            is_pinned=index < pinned,
        )
        for index, session_id in enumerate(term.session_ids)
    ]


class TestTheOrdinaryLife:
    def test_a_term_starts_with_none(self, db: DbSession, autumn: Term) -> None:
        assert repo.list_timetables(db, term_id=autumn.term_id) == []

    def test_created_empty_and_read_back(self, db: DbSession, autumn: Term) -> None:
        made = repo.create_timetable(db, term_id=autumn.term_id, name="Draft A")

        assert made.id is not None
        assert made.status is TimetableStatus.DRAFT
        assert made.penalty is None, "never solved is not the same as costing nothing"
        assert made.created_at is not None
        assert repo.get_timetable(db, int(made.id)) == made
        assert repo.assignment_count(db, int(made.id)) == 0

    def test_listed_newest_first(self, db: DbSession, autumn: Term) -> None:
        """A term accumulates drafts and the interesting one is the one just generated."""
        first = repo.create_timetable(db, term_id=autumn.term_id, name="Draft A")
        second = repo.create_timetable(db, term_id=autumn.term_id, name="Draft B")

        assert [t.id for t in repo.list_timetables(db, term_id=autumn.term_id)] == [
            second.id,
            first.id,
        ]

    def test_narrowed_by_status(self, db: DbSession, autumn: Term) -> None:
        draft = repo.create_timetable(db, term_id=autumn.term_id)
        assert draft.id is not None
        repo.update_timetable(db, int(draft.id), changes={"status": TimetableStatus.ARCHIVED})

        assert repo.list_timetables(db, term_id=autumn.term_id, status=TimetableStatus.DRAFT) == []
        assert (
            len(repo.list_timetables(db, term_id=autumn.term_id, status=TimetableStatus.ARCHIVED))
            == 1
        )

    def test_renamed(self, db: DbSession, autumn: Term) -> None:
        made = repo.create_timetable(db, term_id=autumn.term_id, name="Draft A")
        assert made.id is not None

        renamed = repo.update_timetable(db, int(made.id), changes={"name": "What we ran"})

        assert renamed.name == "What we ran"
        assert renamed.status is TimetableStatus.DRAFT

    def test_publishing_stamps_the_time_and_unpublishing_clears_it(
        self, db: DbSession, autumn: Term
    ) -> None:
        made = repo.create_timetable(db, term_id=autumn.term_id)
        assert made.id is not None

        published = repo.update_timetable(
            db, int(made.id), changes={"status": TimetableStatus.PUBLISHED}
        )
        assert published.published_at is not None
        assert published.is_editable is False

        back = repo.update_timetable(db, int(made.id), changes={"status": TimetableStatus.DRAFT})
        assert back.published_at is None

    def test_deleted_with_everything_in_it(self, db: DbSession, autumn: Term) -> None:
        made = repo.record(db, term_id=autumn.term_id, placements=placed(autumn))
        assert made.id is not None
        db.commit()

        repo.delete_timetable(db, int(made.id))
        db.commit()

        assert repo.list_timetables(db, term_id=autumn.term_id) == []
        assert repo.assignments_of(db, int(made.id)) == []


class TestWhatItRefuses:
    def test_a_timetable_that_is_not_there(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.get_timetable(db, 404)

    def test_a_term_that_is_not_there(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.create_timetable(db, term_id=404)

    def test_an_empty_name(self, db: DbSession, autumn: Term) -> None:
        """The domain owns what a name may be, so this is refused where that rule lives."""
        with pytest.raises(RuleViolationError):
            repo.create_timetable(db, term_id=autumn.term_id, name="")

    def test_a_parent_in_another_term(
        self, db: DbSession, autumn: Term, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """A comparison drawing two timetables of different terms side by side compares
        nothing, and `parent_id` is a plain foreign key with nothing to stop it."""
        spring = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Spring",
        )
        assert spring.id is not None
        elsewhere = repo.create_timetable(db, term_id=int(spring.id))
        assert elsewhere.id is not None

        with pytest.raises(ConflictError):
            repo.create_timetable(db, term_id=autumn.term_id, parent_id=int(elsewhere.id))

    def test_a_placement_naming_another_terms_session(
        self, db: DbSession, autumn: Term, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """The composite key refuses this at commit, naming a constraint. This names the id."""
        spring = term_with_sessions(db, institution, grid, label="Spring")

        with pytest.raises(InvalidReferenceError) as refused:
            repo.record(
                db,
                term_id=autumn.term_id,
                placements=[
                    Assignment(
                        session_id=SessionId(spring.session_ids[0]),
                        start_slot=0,
                        room_id=RoomId(autumn.room_ids[0]),
                    )
                ],
            )
        assert refused.value.field == "session_id"

    def test_deleting_something_an_institution_is_running(
        self, db: DbSession, autumn: Term
    ) -> None:
        made = repo.create_timetable(db, term_id=autumn.term_id)
        assert made.id is not None
        repo.update_timetable(db, int(made.id), changes={"status": TimetableStatus.PUBLISHED})

        with pytest.raises(ConflictError):
            repo.delete_timetable(db, int(made.id))


class TestRecordingAResult:
    def test_every_placement_is_stored(self, db: DbSession, autumn: Term) -> None:
        stored = repo.record(
            db,
            term_id=autumn.term_id,
            placements=placed(autumn),
            name="Generated",
            penalty=1180,
            penalty_breakdown={"minimise_group_gaps": 900, "minimise_room_moves": 280},
        )
        assert stored.id is not None
        db.commit()

        assert stored.penalty == 1180
        assert sum(stored.penalty_breakdown.values()) == 1180
        assert repo.assignment_count(db, int(stored.id)) == len(autumn.session_ids)

    def test_a_term_with_no_sessions_records_an_empty_timetable(
        self, db: DbSession, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """Nothing to place is not a failure to place things. It is also not reachable from a
        solve — `Solution` refuses a solved timetable with no placements — so it is the
        repository being usable on its own rather than a case the solver produces."""
        empty = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Winter",
        )
        assert empty.id is not None

        stored = repo.record(db, term_id=int(empty.id), placements=[])
        assert stored.id is not None

        assert repo.assignment_count(db, int(stored.id)) == 0

    def test_pins_survive_being_written_down(self, db: DbSession, autumn: Term) -> None:
        """Otherwise pin-and-re-optimise works exactly once: the second solve is free to move
        what the first was told to keep."""
        stored = repo.record(db, term_id=autumn.term_id, placements=placed(autumn, pinned=2))
        assert stored.id is not None
        db.commit()

        read_back = repo.assignments_of(db, int(stored.id))

        assert [a.is_pinned for a in read_back].count(True) == 2

    def test_a_refused_result_leaves_nothing_behind(
        self, db: DbSession, autumn: Term, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """The whole result or none of it.

        `record` writes the timetable row before its placements, so a refusal in between is
        exactly where a half-written timetable would come from — a term with some sessions
        placed and some not, which the validator calls *incomplete* and 4.1's D6 made a
        separate question precisely so it could not be passed off as feasible.
        """
        spring = term_with_sessions(db, institution, grid, label="Spring")
        good = placed(autumn)

        with pytest.raises(InvalidReferenceError):
            repo.record(
                db,
                term_id=autumn.term_id,
                placements=[
                    *good,
                    Assignment(
                        session_id=SessionId(spring.session_ids[0]),
                        start_slot=0,
                        room_id=RoomId(autumn.room_ids[0]),
                    ),
                ],
            )
        db.rollback()

        assert repo.list_timetables(db, term_id=autumn.term_id) == []

    def test_a_result_never_replaces_what_it_came_from(self, db: DbSession, autumn: Term) -> None:
        """4.7 D5, and what `parent_id` was put in the first migration for.

        Re-optimising around somebody's pins has to leave the thing they had where it was, or
        *"Keep Result"* is a decision they have already made by the time they are asked.
        """
        original = repo.record(db, term_id=autumn.term_id, placements=placed(autumn), penalty=200)
        assert original.id is not None

        again = repo.record(
            db,
            term_id=autumn.term_id,
            placements=placed(autumn),
            parent_id=int(original.id),
            penalty=180,
        )
        db.commit()

        assert again.id != original.id
        assert again.parent_id == original.id
        assert repo.get_timetable(db, int(original.id)).penalty == 200
        assert len(repo.list_timetables(db, term_id=autumn.term_id)) == 2
