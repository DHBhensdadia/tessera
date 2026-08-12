"""Rooms, instructors, courses and the organisational scaffolding around them.

Handlers are thin on purpose: translate the wire model, call the repository, translate
back. Anything that decides something belongs in `tessera.repository.structure`, where
the CLI and the importers can reach it too.

Failures are raised by the repository in its own vocabulary and translated once, at the
application edge, by the handlers registered in `tessera.api.errors`.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session as DbSession

from tessera.api.deps import Db
from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending
from tessera.api.schemas import (
    BuildingCreate,
    BuildingRead,
    CourseCreate,
    CourseRead,
    CourseUpdate,
    DepartmentCreate,
    DepartmentRead,
    FeatureCreate,
    FeatureRead,
    InstitutionCreate,
    InstitutionRead,
    InstructorCreate,
    InstructorRead,
    InstructorUpdate,
    Page,
    ProgramCreate,
    ProgramRead,
    Reference,
    RoomCreate,
    RoomRead,
    RoomUpdate,
)
from tessera.domain import entities as d
from tessera.repository import models as m
from tessera.repository import people as people_repo
from tessera.repository import structure as repo

router = APIRouter(prefix="/api/v1", tags=["structure"])
ERRORS = problem_responses(404, 409, 422, 501)


def _page[T](items: list[T]) -> Page[T]:
    return Page(items=items, total=len(items))


def _room_read(session: DbSession, room: d.Room) -> RoomRead:
    """Expand ids into references so a list of rooms is renderable in one request.

    A client showing a room table needs the building's name and each feature's name. If
    the response carried only ids it would issue a request per related record, which for
    a few hundred rooms is hundreds of round trips to draw one screen.
    """
    assert room.id is not None  # everything the repository returns has been flushed
    building = session.get(m.Building, room.building_id) if room.building_id else None
    features = (
        session.query(m.Feature).filter(m.Feature.id.in_(room.features)).all()
        if room.features
        else []
    )
    return RoomRead(
        id=room.id,
        name=room.name,
        capacity=room.capacity,
        building=Reference(id=building.id, name=building.name) if building else None,
        features=[Reference(id=f.id, name=f.name) for f in features],
    )


# -- institutions and departments ----------------------------------------------


@router.get("/institutions", response_model=Page[InstitutionRead], responses=ERRORS)
def list_institutions(db: Db) -> Page[InstitutionRead]:
    return _page([InstitutionRead.model_validate(x) for x in repo.list_institutions(db)])


@router.post(
    "/institutions",
    response_model=InstitutionRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_institution(payload: InstitutionCreate, db: Db) -> InstitutionRead:
    return InstitutionRead.model_validate(repo.create_institution(db, name=payload.name))


@router.get("/departments", response_model=Page[DepartmentRead], responses=ERRORS)
def list_departments(db: Db, institution_id: int | None = None) -> Page[DepartmentRead]:
    return _page(
        [
            DepartmentRead.model_validate(x)
            for x in repo.list_departments(db, institution_id=institution_id)
        ]
    )


@router.post(
    "/departments",
    response_model=DepartmentRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_department(payload: DepartmentCreate, db: Db) -> DepartmentRead:
    return DepartmentRead.model_validate(
        repo.create_department(
            db, institution_id=payload.institution_id, name=payload.name, code=payload.code
        )
    )


# -- buildings and features ------------------------------------------------------


@router.get("/buildings", response_model=Page[BuildingRead], responses=ERRORS)
def list_buildings(db: Db, institution_id: int | None = None) -> Page[BuildingRead]:
    return _page(
        [
            BuildingRead.model_validate(x)
            for x in repo.list_buildings(db, institution_id=institution_id)
        ]
    )


@router.post(
    "/buildings",
    response_model=BuildingRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_building(payload: BuildingCreate, db: Db) -> BuildingRead:
    return BuildingRead.model_validate(
        repo.create_building(db, institution_id=payload.institution_id, name=payload.name)
    )


@router.get("/features", response_model=Page[FeatureRead], responses=ERRORS)
def list_features(db: Db, institution_id: int | None = None) -> Page[FeatureRead]:
    return _page(
        [
            FeatureRead.model_validate(x)
            for x in repo.list_features(db, institution_id=institution_id)
        ]
    )


@router.post(
    "/features",
    response_model=FeatureRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_feature(payload: FeatureCreate, db: Db) -> FeatureRead:
    return FeatureRead.model_validate(
        repo.create_feature(db, institution_id=payload.institution_id, name=payload.name)
    )


# -- programs (2.3) --------------------------------------------------------------


@router.get("/programs", response_model=Page[ProgramRead], responses=ERRORS)
def list_programs() -> Page[ProgramRead]:
    pending("2.3")


@router.post(
    "/programs",
    response_model=ProgramRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_program(payload: ProgramCreate) -> ProgramRead:
    pending("2.3")


# -- rooms -----------------------------------------------------------------------


@router.get("/rooms", response_model=Page[RoomRead], responses=ERRORS)
def list_rooms(
    db: Db,
    building_id: int | None = None,
    min_capacity: int | None = None,
    feature_id: list[int] | None = Query(
        default=None,
        description="Repeat to require several. Matches rooms providing *at least* these.",
    ),
) -> Page[RoomRead]:
    """Filtered so the solver and the room picker can ask for candidates directly
    rather than fetching every room and narrowing client-side."""
    rooms = repo.list_rooms(
        db,
        building_id=building_id,
        min_capacity=min_capacity,
        required_features=feature_id,
    )
    return _page([_room_read(db, room) for room in rooms])


@router.post(
    "/rooms", response_model=RoomRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_room(payload: RoomCreate, db: Db) -> RoomRead:
    created = repo.create_room(
        db,
        name=payload.name,
        capacity=payload.capacity,
        building_id=payload.building_id,
        feature_ids=payload.feature_ids,
    )
    return _room_read(db, created)


@router.get("/rooms/{room_id}", response_model=RoomRead, responses=ERRORS)
def get_room(room_id: int, db: Db) -> RoomRead:
    return _room_read(db, repo.get_room(db, room_id))


@router.patch("/rooms/{room_id}", response_model=RoomRead, responses=ERRORS)
def update_room(room_id: int, payload: RoomUpdate, db: Db) -> RoomRead:
    """``exclude_unset`` is what makes this a PATCH rather than a replace.

    It reports only the fields the client actually sent, so an absent field is left
    alone while a field explicitly set to null is cleared. Checking for None instead
    would make those two indistinguishable.
    """
    updated = repo.update_room(db, room_id, changes=payload.model_dump(exclude_unset=True))
    return _room_read(db, updated)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_room(room_id: int, db: Db) -> None:
    repo.delete_room(db, room_id)


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_feature(feature_id: int, db: Db) -> None:
    repo.delete_feature(db, feature_id)


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_building(building_id: int, db: Db) -> None:
    repo.delete_building(db, building_id)


# -- instructors (2.2) -----------------------------------------------------------


@router.get("/instructors", response_model=Page[InstructorRead], responses=ERRORS)
def list_instructors(db: Db, department_id: int | None = None) -> Page[InstructorRead]:
    return _page(
        [
            InstructorRead.model_validate(x)
            for x in people_repo.list_instructors(db, department_id=department_id)
        ]
    )


@router.post(
    "/instructors",
    response_model=InstructorRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_instructor(payload: InstructorCreate, db: Db) -> InstructorRead:
    return InstructorRead.model_validate(
        people_repo.create_instructor(
            db,
            name=payload.name,
            email=payload.email,
            department_id=payload.department_id,
            max_slots_per_day=payload.max_slots_per_day,
            max_slots_per_week=payload.max_slots_per_week,
            max_consecutive_slots=payload.max_consecutive_slots,
        )
    )


@router.get("/instructors/{instructor_id}", response_model=InstructorRead, responses=ERRORS)
def get_instructor(instructor_id: int, db: Db) -> InstructorRead:
    return InstructorRead.model_validate(people_repo.get_instructor(db, instructor_id))


@router.patch("/instructors/{instructor_id}", response_model=InstructorRead, responses=ERRORS)
def update_instructor(instructor_id: int, payload: InstructorUpdate, db: Db) -> InstructorRead:
    return InstructorRead.model_validate(
        people_repo.update_instructor(
            db, instructor_id, changes=payload.model_dump(exclude_unset=True)
        )
    )


@router.delete(
    "/instructors/{instructor_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
def delete_instructor(instructor_id: int, db: Db) -> None:
    people_repo.delete_instructor(db, instructor_id)


# -- courses (2.4) ---------------------------------------------------------------


@router.get("/courses", response_model=Page[CourseRead], responses=ERRORS)
def list_courses(department_id: int | None = None) -> Page[CourseRead]:
    pending("2.4")


@router.post(
    "/courses", response_model=CourseRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_course(payload: CourseCreate) -> CourseRead:
    pending("2.4")


@router.get("/courses/{course_id}", response_model=CourseRead, responses=ERRORS)
def get_course(course_id: int) -> CourseRead:
    pending("2.4")


@router.patch("/courses/{course_id}", response_model=CourseRead, responses=ERRORS)
def update_course(course_id: int, payload: CourseUpdate) -> CourseRead:
    pending("2.4")


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_course(course_id: int) -> None:
    pending("2.4")
