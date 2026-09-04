"""Put one small term into a project file, so the smoke test has something to solve.

Not part of the shipped application — a build-time helper for `smoke-test.sh`, which needs a
term with real teaching in it to prove the *frozen* engine can solve. Seeding through the API
would be a dozen curl calls testing the seeding rather than the bundle.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tessera import engine as engine_module
from tessera import project as project_module
from tessera.domain.entities import SessionKind
from tessera.repository import (
    calendar,
    constraints,
    expansion,
    groups,
    people,
    sessions,
    structure,
    teaching,
)
from tessera.repository.database import create_project_engine, session_factory


def main(path: Path) -> None:
    database = project_module.resolve(path)
    engine_module.migrate(database)
    connection = create_project_engine(database)
    with session_factory(connection)() as db:
        institution = structure.create_institution(db, name="Sardar Patel University")
        assert institution.id is not None
        grid = calendar.create_time_grid(
            db,
            institution_id=int(institution.id),
            name="Standard",
            days=5,
            slots_per_day=8,
            slot_minutes=60,
            day_start_minute=9 * 60,
        )
        department = structure.create_department(
            db, institution_id=int(institution.id), name="Computer Science"
        )
        building = structure.create_building(
            db, institution_id=int(institution.id), name="Main Block"
        )
        assert grid.id is not None and department.id is not None and building.id is not None
        for number in (1, 2):
            structure.create_room(
                db, building_id=int(building.id), name=f"LH-{number}", capacity=60
            )
        program = groups.create_program(db, department_id=int(department.id), name="B.Tech CSE")
        assert program.id is not None
        cohort = groups.create_group(db, name="Sem 5", size=40, program_id=int(program.id))
        instructor = people.create_instructor(
            db, name="Prof. Sharma", department_id=int(department.id)
        )
        term = calendar.create_term(
            db,
            institution_id=int(institution.id),
            time_grid_id=int(grid.id),
            academic_year="2026-27",
            name="Autumn",
        )
        course = teaching.create_course(db, code="CS301", name="Operating Systems")
        assert term.id is not None and course.id is not None
        offering = calendar.create_offering(db, term_id=int(term.id), course_id=int(course.id))
        assert offering.id is not None and cohort.id is not None and instructor.id is not None
        sessions.create_template(
            db,
            offering_id=int(offering.id),
            kind=SessionKind.LECTURE,
            duration_slots=2,
            per_week=4,
            attendee_ids=[int(cohort.id)],
            instructor_ids=[int(instructor.id)],
        )
        expansion.expand(db, int(offering.id))
        constraints.seed_default_constraints(db, int(term.id))
        db.commit()
    connection.dispose()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
