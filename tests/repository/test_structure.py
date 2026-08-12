"""Reading and writing rooms and the scaffolding around them.

Repository-level, so the rules are tested without HTTP in the way. The same rules are
checked again through the API in `tests/api/test_structure.py`, which is not duplication:
one proves the behaviour, the other proves it survives translation to and from the wire.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session as DbSession

from tessera.domain.ids import FeatureId
from tessera.repository import models as m
from tessera.repository import structure as repo
from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError


def ident(entity: object) -> int:
    """The id of something the repository just returned.

    Domain ids are optional because an unsaved entity has none; anything handed back by
    the repository has been flushed and therefore does. Narrowed here once instead of
    scattering assertions through the tests.
    """
    value = getattr(entity, "id", None)
    assert value is not None
    return int(value)


@pytest.fixture
def building(db: DbSession, institution: m.Institution) -> m.Building:
    return repo.create_building(db, institution_id=institution.id, name="Block A")  # type: ignore[return-value]


class TestNaming:
    def test_a_room_name_may_repeat_across_buildings(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        """Room numbers repeat between buildings constantly, which is why the
        constraint is scoped rather than global."""
        a = repo.create_building(db, institution_id=institution.id, name="Block A")
        b = repo.create_building(db, institution_id=institution.id, name="Block B")

        repo.create_room(db, name="101", capacity=40, building_id=a.id)
        repo.create_room(db, name="101", capacity=40, building_id=b.id)

        assert len(repo.list_rooms(db)) == 2

    def test_a_room_name_may_not_repeat_within_one(
        self, db: DbSession, institution: m.Institution
    ) -> None:
        block = repo.create_building(db, institution_id=institution.id, name="Block A")
        repo.create_room(db, name="LH-201", capacity=120, building_id=block.id)

        with pytest.raises(ConflictError, match="already exists"):
            repo.create_room(db, name="LH-201", capacity=60, building_id=block.id)

    def test_unattached_rooms_are_still_refused_a_duplicate_name(self, db: DbSession) -> None:
        """Stricter than the database can be, and deliberately so.

        `building_id` is nullable and SQL treats NULL as distinct from NULL, so the
        unique constraint genuinely cannot reach rooms with no building. The
        application-level check can, because SQLAlchemy renders `== None` as `IS NULL`.

        So this case is protected by one layer rather than two. Anything writing rooms
        without going through this module would not be — nothing does today, and the
        importer in 2.6 must not become the first.
        """
        repo.create_room(db, name="Portacabin", capacity=30)

        with pytest.raises(ConflictError):
            repo.create_room(db, name="Portacabin", capacity=30)

    def test_the_database_alone_would_allow_it(self, db: DbSession) -> None:
        """Proves the layer above is doing the work, not the constraint.

        Written so that if someone later removes the application check believing the
        constraint covers it, this test shows that it does not.
        """
        db.add_all([m.Room(name="Portacabin", capacity=30), m.Room(name="Portacabin", capacity=30)])
        db.flush()  # no IntegrityError: NULL != NULL
        assert len(repo.list_rooms(db)) == 2

    def test_two_institutions_may_each_have_a_main_building(self, db: DbSession) -> None:
        one = repo.create_institution(db, name="First University")
        two = repo.create_institution(db, name="Second University")
        repo.create_building(db, institution_id=ident(one), name="Main")
        repo.create_building(db, institution_id=ident(two), name="Main")
        assert len(repo.list_buildings(db)) == 2


class TestReferences:
    def test_an_unknown_feature_is_reported_against_its_field(
        self, db: DbSession, building: m.Building
    ) -> None:
        """A foreign-key error names a constraint; this names the field the caller sent,
        which is what an import report needs."""
        with pytest.raises(InvalidReferenceError) as raised:
            repo.create_room(db, name="LH-1", capacity=10, feature_ids=[999_999])

        assert raised.value.field == "feature_ids"
        assert raised.value.missing == [999_999]

    def test_an_unknown_building_is_a_missing_record(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.create_room(db, name="LH-1", capacity=10, building_id=999_999)

    def test_reading_a_room_that_does_not_exist(self, db: DbSession) -> None:
        with pytest.raises(NotFoundError):
            repo.get_room(db, 999_999)


class TestFiltering:
    @pytest.fixture
    def stocked(
        self, db: DbSession, institution: m.Institution, features: dict[str, m.Feature]
    ) -> dict[str, int]:
        projector = FeatureId(features["projector"].id)
        computers = FeatureId(features["computers"].id)
        rooms = {
            "lecture": repo.create_room(db, name="LH-201", capacity=120, feature_ids=[projector]),
            "lab": repo.create_room(
                db, name="CL-01", capacity=40, feature_ids=[projector, computers]
            ),
            "seminar": repo.create_room(db, name="SR-1", capacity=25),
        }
        return {name: room.id for name, room in rooms.items()}  # type: ignore[misc]

    def test_capacity_filters_out_rooms_that_are_too_small(
        self, db: DbSession, stocked: dict[str, int]
    ) -> None:
        assert {r.name for r in repo.list_rooms(db, min_capacity=100)} == {"LH-201"}
        assert {r.name for r in repo.list_rooms(db, min_capacity=30)} == {"LH-201", "CL-01"}

    def test_one_required_feature(
        self, db: DbSession, stocked: dict[str, int], features: dict[str, m.Feature]
    ) -> None:
        found = repo.list_rooms(db, required_features=[features["projector"].id])
        assert {r.name for r in found} == {"LH-201", "CL-01"}

    def test_several_features_means_all_of_them(
        self, db: DbSession, stocked: dict[str, int], features: dict[str, m.Feature]
    ) -> None:
        """The point of the HAVING COUNT form: *at least* these, not any of them.

        A naive `IN` would return both rooms, since LH-201 has one of the two.
        """
        found = repo.list_rooms(
            db, required_features=[features["projector"].id, features["computers"].id]
        )
        assert {r.name for r in found} == {"CL-01"}

    def test_a_repeated_feature_does_not_change_the_answer(
        self, db: DbSession, stocked: dict[str, int], features: dict[str, m.Feature]
    ) -> None:
        """Guards the HAVING count against duplicates in the request."""
        pid = features["projector"].id
        assert len(repo.list_rooms(db, required_features=[pid, pid])) == 2

    def test_capacity_and_features_together(
        self, db: DbSession, stocked: dict[str, int], features: dict[str, m.Feature]
    ) -> None:
        found = repo.list_rooms(db, min_capacity=100, required_features=[features["projector"].id])
        assert {r.name for r in found} == {"LH-201"}

    def test_can_host_agrees_with_the_query(
        self, db: DbSession, stocked: dict[str, int], features: dict[str, m.Feature]
    ) -> None:
        """The SQL filter and `Room.can_host` express the same rule in two places.

        The solver uses one and the room picker the other; if they disagree, a room
        offered in the interface is rejected by the solver. This is what stops that.
        """
        required = frozenset({FeatureId(features["projector"].id)})
        matched = repo.rooms_that_can_host(db, headcount=100, required_features=list(required))

        for room in repo.list_rooms(db):
            assert room.can_host(100, required) == (room.name in {r.name for r in matched})


class TestUpdating:
    def test_only_the_fields_sent_are_touched(self, db: DbSession, building: m.Building) -> None:
        """What makes this PATCH rather than replace."""
        room = repo.create_room(db, name="LH-201", capacity=120, building_id=building.id)

        updated = repo.update_room(db, ident(room), changes={"capacity": 150})

        assert updated.capacity == 150
        assert updated.name == "LH-201"
        assert updated.building_id == building.id

    def test_a_field_set_to_null_is_cleared(self, db: DbSession, building: m.Building) -> None:
        """Distinguishable from "not sent" only because `exclude_unset` reports it."""
        room = repo.create_room(db, name="LH-201", capacity=120, building_id=building.id)

        updated = repo.update_room(db, ident(room), changes={"building_id": None})

        assert updated.building_id is None

    def test_renaming_onto_an_existing_name_is_refused(
        self, db: DbSession, building: m.Building
    ) -> None:
        repo.create_room(db, name="LH-201", capacity=120, building_id=building.id)
        other = repo.create_room(db, name="LH-202", capacity=120, building_id=building.id)

        with pytest.raises(ConflictError):
            repo.update_room(db, ident(other), changes={"name": "LH-201"})

    def test_a_room_may_keep_its_own_name(self, db: DbSession, building: m.Building) -> None:
        """The duplicate check must exclude the row being updated, or every edit that
        leaves the name alone would collide with itself."""
        room = repo.create_room(db, name="LH-201", capacity=120, building_id=building.id)
        updated = repo.update_room(db, ident(room), changes={"name": "LH-201", "capacity": 90})
        assert updated.capacity == 90

    def test_features_are_replaced_wholesale(
        self, db: DbSession, features: dict[str, m.Feature]
    ) -> None:
        room = repo.create_room(
            db, name="CL-01", capacity=40, feature_ids=[features["projector"].id]
        )
        updated = repo.update_room(
            db, ident(room), changes={"feature_ids": [features["computers"].id]}
        )
        assert updated.features == frozenset({FeatureId(features["computers"].id)})


class TestDeleting:
    def test_an_unused_room_is_removed(self, db: DbSession) -> None:
        room = repo.create_room(db, name="LH-201", capacity=120)
        repo.delete_room(db, ident(room))
        assert repo.list_rooms(db) == []

    def test_a_scheduled_room_is_refused_and_says_how_many(
        self, db: DbSession, term: m.Term
    ) -> None:
        """The database would refuse this anyway, as a constraint violation naming an
        index. Counting first is what turns it into something a user can act on."""
        room = repo.create_room(db, name="LH-201", capacity=120)
        course = m.Course(code="CS301", name="Operating Systems")
        db.add(course)
        db.flush()
        offering = m.Offering(term_id=term.id, course_id=course.id)
        db.add(offering)
        db.flush()
        session_row = m.Session(offering_id=offering.id, term_id=term.id, duration_slots=2)
        timetable = m.Timetable(term_id=term.id, name="Draft")
        db.add_all([session_row, timetable])
        db.flush()
        db.add(
            m.Assignment(
                timetable_id=timetable.id,
                session_id=session_row.id,
                term_id=term.id,
                start_slot=0,
                room_id=room.id,
            )
        )
        db.flush()

        with pytest.raises(ConflictError) as raised:
            repo.delete_room(db, ident(room))

        assert raised.value.blockers == {"assignments": 1}

    def test_a_feature_in_use_is_refused(
        self, db: DbSession, features: dict[str, m.Feature]
    ) -> None:
        repo.create_room(db, name="CL-01", capacity=40, feature_ids=[features["projector"].id])

        with pytest.raises(ConflictError) as raised:
            repo.delete_feature(db, features["projector"].id)

        assert raised.value.blockers["rooms"] == 1

    def test_deleting_a_building_leaves_its_rooms_unattached(
        self, db: DbSession, building: m.Building
    ) -> None:
        """Rooms outlive their building on purpose.

        `room.building_id` is ON DELETE SET NULL. Losing a hundred rooms because a
        building was removed would be a far worse outcome than a hundred rooms briefly
        lacking an address.
        """
        repo.create_room(db, name="LH-201", capacity=120, building_id=building.id)

        repo.delete_building(db, ident(building))
        db.expire_all()

        rooms = repo.list_rooms(db)
        assert len(rooms) == 1
        assert rooms[0].building_id is None
