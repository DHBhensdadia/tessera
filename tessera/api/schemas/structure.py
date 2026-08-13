"""Institutions, rooms, instructors, courses — the things that outlive a term."""

from __future__ import annotations

from pydantic import Field

from tessera.api.schemas.common import Reference, Wire


class InstitutionCreate(Wire):
    name: str = Field(min_length=1, max_length=200)


class InstitutionUpdate(Wire):
    """Only the name.

    Every ``*Update`` below carries the entity's own fields and never its parent. Moving
    a department to another institution would silently take its programmes, groups and
    rooms with it — the same hazard as re-pointing a term at another grid (Decision #51),
    and out of scope for the same reason.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)


class InstitutionRead(Wire):
    id: int
    name: str


class DepartmentCreate(Wire):
    institution_id: int
    name: str = Field(min_length=1, max_length=200)
    code: str = ""


class DepartmentUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = None


class DepartmentRead(Wire):
    id: int
    institution_id: int
    name: str
    code: str


class BuildingCreate(Wire):
    institution_id: int
    name: str = Field(min_length=1, max_length=200)


class BuildingUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class BuildingRead(Wire):
    id: int
    institution_id: int
    name: str


class FeatureCreate(Wire):
    institution_id: int
    name: str = Field(min_length=1, max_length=100)


class FeatureUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class FeatureRead(Wire):
    id: int
    institution_id: int
    name: str


class ProgramCreate(Wire):
    department_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    code: str = ""


class ProgramUpdate(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = None


class ProgramRead(Wire):
    id: int
    department_id: int | None
    name: str
    code: str


class RoomCreate(Wire):
    building_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    capacity: int = Field(ge=0)
    feature_ids: list[int] = Field(
        default_factory=list,
        description="Capabilities this room provides. Matched by subset against a "
        "session's requirements — see ADR on capability sets.",
    )


class RoomUpdate(Wire):
    building_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    capacity: int | None = Field(default=None, ge=0)
    feature_ids: list[int] | None = None


class RoomRead(Wire):
    id: int
    name: str
    capacity: int
    building: Reference | None = None
    features: list[Reference] = Field(default_factory=list)


class InstructorCreate(Wire):
    department_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    email: str = ""
    max_slots_per_day: int | None = Field(default=None, ge=1)
    max_slots_per_week: int | None = Field(default=None, ge=1)
    max_consecutive_slots: int | None = Field(default=None, ge=1)


class InstructorUpdate(Wire):
    department_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = None
    max_slots_per_day: int | None = Field(default=None, ge=1)
    max_slots_per_week: int | None = Field(default=None, ge=1)
    max_consecutive_slots: int | None = Field(default=None, ge=1)


class InstructorRead(Wire):
    id: int
    name: str
    email: str
    department: Reference | None = None
    max_slots_per_day: int | None
    max_slots_per_week: int | None
    max_consecutive_slots: int | None


class CourseCreate(Wire):
    department_id: int | None = None
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    credits: int = Field(default=0, ge=0)


class CourseUpdate(Wire):
    department_id: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    credits: int | None = Field(default=None, ge=0)


class CourseRead(Wire):
    id: int
    code: str
    name: str
    credits: int
    department: Reference | None = None
