"""Rooms, instructors, courses and the organisational scaffolding around them.

CRUD arrives in Stage 2; the shapes are fixed here so the client and the HTML console
can be written against them first.
"""

from __future__ import annotations

from fastapi import APIRouter, status

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
    RoomCreate,
    RoomRead,
    RoomUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["structure"])
ERRORS = problem_responses(404, 422, 501)


@router.get("/institutions", response_model=Page[InstitutionRead], responses=ERRORS)
def list_institutions() -> Page[InstitutionRead]:
    pending("2.1")


@router.post(
    "/institutions",
    response_model=InstitutionRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_institution(payload: InstitutionCreate) -> InstitutionRead:
    pending("2.1")


@router.get("/departments", response_model=Page[DepartmentRead], responses=ERRORS)
def list_departments() -> Page[DepartmentRead]:
    pending("2.1")


@router.post(
    "/departments",
    response_model=DepartmentRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_department(payload: DepartmentCreate) -> DepartmentRead:
    pending("2.1")


@router.get("/buildings", response_model=Page[BuildingRead], responses=ERRORS)
def list_buildings() -> Page[BuildingRead]:
    pending("2.1")


@router.post(
    "/buildings",
    response_model=BuildingRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_building(payload: BuildingCreate) -> BuildingRead:
    pending("2.1")


@router.get("/features", response_model=Page[FeatureRead], responses=ERRORS)
def list_features() -> Page[FeatureRead]:
    pending("2.1")


@router.post(
    "/features",
    response_model=FeatureRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_feature(payload: FeatureCreate) -> FeatureRead:
    pending("2.1")


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


# -- rooms --------------------------------------------------------------------


@router.get("/rooms", response_model=Page[RoomRead], responses=ERRORS)
def list_rooms(
    building_id: int | None = None,
    min_capacity: int | None = None,
    feature_id: int | None = None,
) -> Page[RoomRead]:
    """Filters exist so the solver and the room picker can ask for candidates directly
    rather than fetching every room and narrowing client-side."""
    pending("2.1")


@router.post(
    "/rooms", response_model=RoomRead, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_room(payload: RoomCreate) -> RoomRead:
    pending("2.1")


@router.get("/rooms/{room_id}", response_model=RoomRead, responses=ERRORS)
def get_room(room_id: int) -> RoomRead:
    pending("2.1")


@router.patch("/rooms/{room_id}", response_model=RoomRead, responses=ERRORS)
def update_room(room_id: int, payload: RoomUpdate) -> RoomRead:
    pending("2.1")


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_room(room_id: int) -> None:
    pending("2.1")


# -- instructors ---------------------------------------------------------------


@router.get("/instructors", response_model=Page[InstructorRead], responses=ERRORS)
def list_instructors(department_id: int | None = None) -> Page[InstructorRead]:
    pending("2.2")


@router.post(
    "/instructors",
    response_model=InstructorRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_instructor(payload: InstructorCreate) -> InstructorRead:
    pending("2.2")


@router.get("/instructors/{instructor_id}", response_model=InstructorRead, responses=ERRORS)
def get_instructor(instructor_id: int) -> InstructorRead:
    pending("2.2")


@router.patch("/instructors/{instructor_id}", response_model=InstructorRead, responses=ERRORS)
def update_instructor(instructor_id: int, payload: InstructorUpdate) -> InstructorRead:
    pending("2.2")


@router.delete(
    "/instructors/{instructor_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
def delete_instructor(instructor_id: int) -> None:
    pending("2.2")


# -- courses -------------------------------------------------------------------


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
