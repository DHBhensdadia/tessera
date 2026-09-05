"""A term built the way the application builds one, for the tests that need a real one.

Constructed through the repository rather than by adding rows, so what these tests read back
went in through the same checks a person's data would — a term assembled by hand can be
internally inconsistent in ways nothing in the product can produce, and a loader tested only
against those is tested against a term that cannot exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import calendar as calendar_repo
from tessera.repository import constraints as constraints_repo
from tessera.repository import expansion
from tessera.repository import groups as groups_repo
from tessera.repository import models as m
from tessera.repository import people as people_repo
from tessera.repository import sessions as sessions_repo
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as teaching_repo


@dataclass(frozen=True)
class Term:
    """The ids a test needs to talk about the term it was given."""

    term_id: int
    offering_id: int
    session_ids: list[int]
    room_ids: list[int]
    group_id: int
    instructor_id: int


def term_with_sessions(
    db: DbSession,
    institution: m.Institution,
    grid: m.TimeGrid,
    *,
    per_week: int = 3,
    rooms: int = 2,
    capacity: int = 60,
    with_rules: bool = True,
    label: str = "",
) -> Term:
    """One offering, `per_week` lectures of it, a room or two, and the default rules.

    `label` distinguishes a second term in the same project. Names are unique within an
    institution, which is a rule worth keeping rather than working around — a test needing two
    terms is a test about two real terms, and they would not share a department name either.
    """
    mark = f" {label}" if label else ""
    department = structure_repo.create_department(
        db, institution_id=institution.id, name=f"Computer Science{mark}"
    )
    building = structure_repo.create_building(db, institution_id=institution.id, name=f"Main{mark}")
    assert department.id is not None and building.id is not None

    room_ids = []
    for number in range(1, rooms + 1):
        room = structure_repo.create_room(
            db, building_id=int(building.id), name=f"LH-{number}{mark}", capacity=capacity
        )
        assert room.id is not None
        room_ids.append(int(room.id))

    program = groups_repo.create_program(
        db, department_id=int(department.id), name=f"B.Tech CSE{mark}"
    )
    assert program.id is not None
    group = groups_repo.create_group(db, name=f"Sem 5{mark}", size=40, program_id=int(program.id))
    instructor = people_repo.create_instructor(
        db, name=f"Prof. Sharma{mark}", department_id=int(department.id)
    )
    assert group.id is not None and instructor.id is not None

    term = calendar_repo.create_term(
        db,
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name=f"Autumn{mark}",
    )
    course = teaching_repo.create_course(db, code=f"CS301{mark}", name=f"Operating Systems{mark}")
    assert term.id is not None and course.id is not None
    offering = calendar_repo.create_offering(db, term_id=int(term.id), course_id=int(course.id))
    assert offering.id is not None

    sessions_repo.create_template(
        db,
        offering_id=int(offering.id),
        kind=d.SessionKind.LECTURE,
        duration_slots=2,
        per_week=per_week,
        attendee_ids=[int(group.id)],
        instructor_ids=[int(instructor.id)],
    )
    made = expansion.expand(db, int(offering.id))
    if with_rules:
        constraints_repo.seed_default_constraints(db, int(term.id))
    db.commit()

    return Term(
        term_id=int(term.id),
        offering_id=int(offering.id),
        session_ids=[int(s.id) for s in made if s.id is not None],
        room_ids=room_ids,
        group_id=int(group.id),
        instructor_id=int(instructor.id),
    )


def refuted_term(db: DbSession, institution: m.Institution, grid: m.TimeGrid) -> Term:
    """A term the counting argument refutes, built through the repository like any other.

    One group, one instructor, one room and more one-hour sessions than the week has hours.
    Every one of the three occupancy invariants is short by the same amount, which is what
    makes it useful for the pre-flight and the infeasibility report alike: the check fires,
    the solve ends `infeasible` rather than out of time, and the report has three requirements
    in it rather than one.

    **The grid it needs is small**, so pass one — `tests.conftest.campus` builds a full
    teaching week and a term with 40 free hours cannot be refuted by five sessions.
    """
    department = structure_repo.create_department(db, institution_id=institution.id, name="Refuted")
    building = structure_repo.create_building(db, institution_id=institution.id, name="Annexe")
    assert department.id is not None and building.id is not None
    room = structure_repo.create_room(
        db, building_id=int(building.id), name="The only room", capacity=60
    )
    program = groups_repo.create_program(db, department_id=int(department.id), name="B.Sc")
    assert program.id is not None
    group = groups_repo.create_group(db, name="One intake", size=40, program_id=int(program.id))
    instructor = people_repo.create_instructor(
        db, name="Prof. Rao", department_id=int(department.id)
    )
    term = calendar_repo.create_term(
        db,
        institution_id=institution.id,
        time_grid_id=grid.id,
        academic_year="2026-27",
        name="Overloaded",
    )
    course = teaching_repo.create_course(db, code="XX999", name="Too much of it")
    assert term.id is not None and course.id is not None and room.id is not None
    offering = calendar_repo.create_offering(db, term_id=int(term.id), course_id=int(course.id))
    assert offering.id is not None and group.id is not None and instructor.id is not None

    sessions_repo.create_template(
        db,
        offering_id=int(offering.id),
        kind=d.SessionKind.LECTURE,
        duration_slots=1,
        per_week=grid.days * grid.slots_per_day + 1,
        attendee_ids=[int(group.id)],
        instructor_ids=[int(instructor.id)],
    )
    made = expansion.expand(db, int(offering.id))
    constraints_repo.seed_default_constraints(db, int(term.id))
    db.commit()

    return Term(
        term_id=int(term.id),
        offering_id=int(offering.id),
        session_ids=[int(s.id) for s in made if s.id is not None],
        room_ids=[int(room.id)],
        group_id=int(group.id),
        instructor_id=int(instructor.id),
    )
