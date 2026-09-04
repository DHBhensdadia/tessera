"""Reading a stored term the way the solver reads one.

**Nothing in the repository built a `Snapshot` before 4.7.** The validator has taken one since
4.1, the model since 4.2 and the pre-flight since 4.6, and the only things that ever built one
were the tests and the benchmark — so the engine had a solver and no way to point it at the
project a person had open. `test_a_term_goes_out_and_comes_back_as_a_timetable` is the test for
that missing half-inch of pipe, and it is 4.7 part 1's exit criterion.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain.ids import InstructorId, RoomId, SessionId, StudentGroupId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import validate
from tessera.repository import models as m
from tessera.repository import people as people_repo
from tessera.repository import snapshot as repo
from tessera.repository import structure as structure_repo
from tessera.repository import timetables as timetables_repo
from tessera.repository.errors import ConflictError, NotFoundError
from tessera.solver import Budget, Outcome, solve
from tests.repository.authored import Term, term_with_sessions


@pytest.fixture
def autumn(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> Term:
    return term_with_sessions(db, institution, grid)


def timetable_of(db: DbSession, term: Term, *, pinned: tuple[int, ...] = ()) -> int:
    made = timetables_repo.record(
        db,
        term_id=term.term_id,
        placements=[
            Assignment(
                session_id=SessionId(session_id),
                start_slot=index * 2,
                room_id=RoomId(term.room_ids[0]),
                is_pinned=session_id in pinned,
            )
            for index, session_id in enumerate(term.session_ids)
        ],
    )
    db.commit()
    assert made.id is not None
    return int(made.id)


class TestWhatArrives:
    def test_the_term_as_the_solver_sees_it(self, db: DbSession, autumn: Term) -> None:
        loaded = repo.load(db, autumn.term_id)

        assert sorted(loaded.sessions) == sorted(SessionId(s) for s in autumn.session_ids)
        assert sorted(loaded.rooms) == sorted(RoomId(r) for r in autumn.room_ids)
        assert loaded.grid.slot_count == 6 * 16
        assert loaded.placements == {}, "a term nobody has solved has nothing placed"

    def test_the_rules_the_term_carries(self, db: DbSession, autumn: Term) -> None:
        loaded = repo.load(db, autumn.term_id)

        assert loaded.constraints, "the defaults were seeded and nothing read them"
        assert all(rule.term_id == autumn.term_id for rule in loaded.constraints)

    def test_which_course_each_session_belongs_to(self, db: DbSession, autumn: Term) -> None:
        """Two of the sixteen scored rules need it — a course in one room, a course not twice
        in a day — and `Snapshot` asks for it rather than deriving it, so forgetting it here
        would price both at zero instead of raising."""
        loaded = repo.load(db, autumn.term_id)

        assert set(loaded.course_of) == {SessionId(s) for s in autumn.session_ids}
        assert len(set(loaded.course_of.values())) == 1

    def test_who_is_teaching_and_who_is_attending(self, db: DbSession, autumn: Term) -> None:
        loaded = repo.load(db, autumn.term_id)

        placed = len(autumn.session_ids)
        assert len(loaded.sessions_of_instructor[InstructorId(autumn.instructor_id)]) == placed
        assert len(loaded.sessions_of_group[StudentGroupId(autumn.group_id)]) == placed

    def test_a_blocked_hour_is_hard_and_a_disliked_one_is_not(
        self, db: DbSession, autumn: Term
    ) -> None:
        """The difference the validator turns on: *cannot* is an invariant and *would rather
        not* is a price. A loader that flattened them would make every stated preference an
        impossibility."""
        people_repo.block_slots(
            db, autumn.term_id, kind="instructor", subject_id=autumn.instructor_id, slots=[0, 1]
        )
        people_repo.block_slots(
            db,
            autumn.term_id,
            kind="instructor",
            subject_id=autumn.instructor_id,
            slots=[20],
            is_hard=False,
            weight=3,
        )
        people_repo.block_slots(
            db, autumn.term_id, kind="room", subject_id=autumn.room_ids[0], slots=[4]
        )
        db.commit()

        loaded = repo.load(db, autumn.term_id)

        assert (InstructorId(autumn.instructor_id), 0) in loaded.instructor_away
        assert (RoomId(autumn.room_ids[0]), 4) in loaded.room_closed
        assert loaded.preferred_against[(InstructorId(autumn.instructor_id), 20)] == 3

    def test_a_term_that_is_not_there(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.load(db, 404)


class TestWhichRoomsBelongToTheTerm:
    def test_another_institutions_rooms_are_not_this_terms(
        self, db: DbSession, autumn: Term
    ) -> None:
        """2.6 settled this for names and the argument is the same for rooms: a project file
        can hold more than one institution, and a timetable placing a class in another
        university's lecture hall is not a rounding error."""
        other = structure_repo.create_institution(db, name="Another University")
        assert other.id is not None
        elsewhere = structure_repo.create_building(
            db, institution_id=int(other.id), name="Their Block"
        )
        assert elsewhere.id is not None
        structure_repo.create_room(
            db, building_id=int(elsewhere.id), name="Their Hall", capacity=500
        )
        db.commit()

        loaded = repo.load(db, autumn.term_id)

        assert sorted(loaded.rooms) == sorted(RoomId(r) for r in autumn.room_ids)

    def test_a_room_with_no_building_is_kept_rather_than_guessed_about(
        self, db: DbSession, autumn: Term
    ) -> None:
        """The chain to an institution runs through a building and the link is optional, so
        where it is broken the question cannot be answered. Dropping the room would be a
        silent loss; `_reject_foreign_groups` is written with the same honesty about its
        edges."""
        homeless = structure_repo.create_room(db, name="Portacabin", capacity=30)
        assert homeless.id is not None
        db.commit()

        loaded = repo.load(db, autumn.term_id)

        assert RoomId(int(homeless.id)) in loaded.rooms


class TestStartingFromATimetable:
    def test_a_seed_arrives_as_the_terms_own_placements(self, db: DbSession, autumn: Term) -> None:
        """What makes re-optimising *re*-optimising: `Formulation.hint` hands these to CP-SAT
        as a starting point, and without them a re-solve begins from nothing."""
        seed = timetable_of(db, autumn)

        loaded = repo.load(db, autumn.term_id, seed_timetable_id=seed)

        assert len(loaded.placements) == len(autumn.session_ids)

    def test_pins_arrive_pinned(self, db: DbSession, autumn: Term) -> None:
        seed = timetable_of(db, autumn, pinned=(autumn.session_ids[0],))

        loaded = repo.load(db, autumn.term_id, seed_timetable_id=seed)

        assert loaded.placements[SessionId(autumn.session_ids[0])].is_pinned is True

    def test_unless_the_caller_says_not_to_respect_them(self, db: DbSession, autumn: Term) -> None:
        """*"Use this as a starting point, but you may move anything."* The warm start and the
        pins are separate on the wire and have to be separate here, or the only way to unpin
        for one solve would be to unpin in the data."""
        seed = timetable_of(db, autumn, pinned=(autumn.session_ids[0],))

        loaded = repo.load(db, autumn.term_id, seed_timetable_id=seed, respect_pins=False)

        assert len(loaded.placements) == len(autumn.session_ids)
        assert not any(p.is_pinned for p in loaded.placements.values())

    def test_a_seed_from_another_term_is_refused_rather_than_ignored(
        self, db: DbSession, autumn: Term, institution: m.Institution, grid: m.TimeGrid
    ) -> None:
        """`Snapshot.of` drops assignments whose session is not in the term, so this would
        otherwise be a solve that silently started from nothing and looked like it had not."""
        spring = term_with_sessions(db, institution, grid, label="Spring")
        elsewhere = timetable_of(db, spring)

        with pytest.raises(ConflictError):
            repo.load(db, autumn.term_id, seed_timetable_id=elsewhere)

    def test_a_seed_that_is_not_there(self, db: DbSession, autumn: Term) -> None:
        with pytest.raises(NotFoundError):
            repo.load(db, autumn.term_id, seed_timetable_id=404)


class TestTheWholeWayRound:
    def test_a_term_goes_out_and_comes_back_as_a_timetable(
        self, db: DbSession, autumn: Term
    ) -> None:
        """4.7 part 1's exit criterion, and the first time the engine has ever done this.

        Out of the database, through the solver, back into the database, and read again as a
        timetable the validator calls complete and free of hard violations. Every previous
        phase could do one of the four.
        """
        term = repo.load(db, autumn.term_id)

        found = solve(term, Budget(seconds=30.0))
        assert found.outcome is Outcome.SOLVED

        stored = timetables_repo.record(
            db,
            term_id=autumn.term_id,
            placements=[
                Assignment(
                    session_id=p.session,
                    start_slot=p.start_slot,
                    room_id=p.room,
                    is_pinned=p.is_pinned,
                )
                for p in found.placements
            ],
            name="Generated",
            penalty=found.penalty,
            penalty_breakdown=found.penalty_breakdown,
        )
        db.commit()
        assert stored.id is not None

        again = repo.load(db, autumn.term_id, seed_timetable_id=int(stored.id))
        report = validate(again)

        assert report.is_complete, f"sessions left unplaced: {report.unplaced}"
        assert report.is_feasible, f"hard violations: {[v.rule for v in report.violations]}"
        assert report.penalty == found.penalty, (
            "the validator and the solver disagree about what this timetable costs, which is "
            "the one thing 4.3's exit test says cannot happen"
        )

    def test_a_pinned_session_is_where_it_was_left(self, db: DbSession, autumn: Term) -> None:
        """Decision #10 put `is_pinned` in the first migration *"because retrofitting reworks
        the solver interface"*. This is the phase where it either pays off or is quietly
        ignored, and the whole path — stored, loaded, fixed by the model, written back — has
        to hold for pin-and-re-optimise to work twice running."""
        pinned_session = autumn.session_ids[0]
        seed = timetable_of(db, autumn, pinned=(pinned_session,))
        before = repo.load(db, autumn.term_id, seed_timetable_id=seed)
        was = before.placements[SessionId(pinned_session)]

        found = solve(before, Budget(seconds=20.0))
        after = {p.session: p for p in found.placements}

        assert found.outcome is Outcome.SOLVED
        assert after[SessionId(pinned_session)].start_slot == was.start_slot
        assert after[SessionId(pinned_session)].room == was.room_id
        assert after[SessionId(pinned_session)].is_pinned is True
