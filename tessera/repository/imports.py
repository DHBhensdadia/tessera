"""Applying an import plan, and reading the project it will be checked against.

Two jobs, both of which the importer itself is forbidden from doing because it may not
import SQLAlchemy: telling it what the project already contains, and writing what it
produced.

**Every write goes through the ordinary repository functions.** Bulk inserts would be
faster and would walk straight past `create_room`, which is the only place the rule "a
room called LH-201 already exists here" exists for a room with no building — SQL treats
each null as distinct, so the unique constraint cannot reach it. The backlog entry that
predicted this names 2.6 as the phase where it would happen. A few hundred rows once per
project is not where speed matters.

**A dry run does exactly what a commit does and then rolls back.** A dry run that checks
less than the commit is worse than no dry run, because it turns "I checked" into
confidence that was never earned.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain import groups as dg
from tessera.importers.detect import Kind
from tessera.importers.plan import Catalogue, Plan, Prepared, Problem
from tessera.repository import groups as groups_repo
from tessera.repository import models as m
from tessera.repository import people as people_repo
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as teaching_repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class Outcome:
    """What happened, or what would have happened."""

    written: int = 0
    problems: tuple[Problem, ...] = ()
    #: True when nothing was written because something failed on the way in.
    rolled_back: bool = False


def catalogue_for(session: DbSession, term_id: int) -> Catalogue:
    """What the project holds, scoped to the institution running this term.

    The institution is the reason `term_id` is on the request at all: rooms and staff are
    not term-scoped, but a project file can hold more than one institution, and `Block A`
    at one of them is not `Block A` at the other. Resolving names across the whole file
    would silently attach a room to a building at a different university.
    """
    term = session.get(m.Term, term_id)
    institution = term.institution_id if term else None

    def by_name(query: Select[tuple[int, str]]) -> dict[str, int]:
        return {name: int(identifier) for identifier, name in session.execute(query)}

    buildings = select(m.Building.id, m.Building.name)
    features = select(m.Feature.id, m.Feature.name)
    departments = select(m.Department.id, m.Department.name)
    if institution is not None:
        buildings = buildings.where(m.Building.institution_id == institution)
        features = features.where(m.Feature.institution_id == institution)
        departments = departments.where(m.Department.institution_id == institution)

    return Catalogue(
        buildings=by_name(buildings),
        features=by_name(features),
        departments=by_name(departments),
        # Programmes and groups reach an institution only through a department, and both
        # links are optional, so they are left unscoped rather than scoped wrongly.
        programs=by_name(select(m.Program.id, m.Program.name)),
        groups=by_name(select(m.StudentGroup.id, m.StudentGroup.name)),
    )


def _ordered(plan: Plan) -> list[Prepared]:
    """Parents before the rows that name them.

    Only groups can depend on a sibling row, and a sheet listing an intake below its own
    batches is common enough to be worth handling rather than refusing. Anything that
    cannot be placed — a cycle typed into a spreadsheet — keeps its file order and is
    refused by the domain when it is written, which is the right place for it.
    """
    if plan.kind is not Kind.GROUPS:
        return list(plan.ready)

    remaining = list(plan.ready)
    placed: list[Prepared] = []
    satisfied: set[str] = set()

    while remaining:
        progressed = False
        for prepared in list(remaining):
            wanted = prepared.pending_parent.casefold().strip()
            if not wanted or wanted in satisfied:
                placed.append(prepared)
                remaining.remove(prepared)
                name = getattr(prepared.entity, "name", "")
                satisfied.add(name.casefold().strip())
                progressed = True
        if not progressed:
            placed.extend(remaining)  # a cycle; let the write refuse it
            break
    return placed


def apply(session: DbSession, plan: Plan, *, dry_run: bool) -> Outcome:
    """Write the plan, or find out what would happen if it were written.

    Rows that failed validation are already absent — they were excluded when the plan was
    built, and reported there. What can still fail here is a rule only the project knows:
    a room whose name is already taken, a group whose parent turns out to be its own
    descendant. **Any of those rolls the whole import back**, so an import is never half
    applied; the caller fixes the file and runs it again.
    """
    written = 0
    created: dict[str, int] = {}

    # A savepoint rather than the whole transaction. `session.rollback()` would undo
    # everything the caller had done before calling this — which for a dry run means an
    # innocent read-and-report could silently discard someone else's unsaved work in the
    # same request. Scoping it to the import is what makes "roll back" mean "roll back
    # *this*".
    savepoint = session.begin_nested()
    try:
        for prepared in _ordered(plan):
            _write(session, prepared, created)
            written += 1
    except RepositoryError as error:
        savepoint.rollback()
        return Outcome(
            written=0,
            problems=(Problem(row=_row_of(plan, written), column="", message=str(error)),),
            rolled_back=True,
        )

    if dry_run:
        savepoint.rollback()
        return Outcome(written=0, rolled_back=True)

    savepoint.commit()  # releases into the surrounding transaction, which commits later
    return Outcome(written=written)


def _row_of(plan: Plan, written: int) -> int:
    """The row that failed, which is the one after everything that succeeded."""
    ordered = _ordered(plan)
    return ordered[written].row if written < len(ordered) else 0


def _write(session: DbSession, prepared: Prepared, created: dict[str, int]) -> None:
    entity = prepared.entity

    if isinstance(entity, d.Room):
        structure_repo.create_room(
            session,
            name=entity.name,
            capacity=entity.capacity,
            building_id=entity.building_id,
            feature_ids=sorted(entity.features),
        )
    elif isinstance(entity, d.Instructor):
        people_repo.create_instructor(
            session, name=entity.name, email=entity.email, department_id=entity.department_id
        )
    elif isinstance(entity, d.Course):
        teaching_repo.create_course(
            session,
            code=entity.code,
            name=entity.name,
            credits=entity.credits,
            department_id=entity.department_id,
        )
    elif isinstance(entity, dg.StudentGroup):
        parent_id = entity.parent_id
        if prepared.pending_parent:
            # Written earlier in this same import; `_ordered` guarantees it exists by now.
            parent_id = created.get(prepared.pending_parent.casefold().strip())  # type: ignore[assignment]
        group = groups_repo.create_group(
            session,
            name=entity.name,
            kind=entity.kind,
            size=entity.size,
            program_id=entity.program_id,
            parent_id=parent_id,
        )
        created[entity.name.casefold().strip()] = int(group.id or 0)
