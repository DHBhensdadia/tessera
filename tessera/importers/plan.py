"""Turning rows of text into things the project could contain, or into reasons it cannot.

The output is a **plan**: what would be written, and every reason a row would not be.
Nothing here writes anything — `tessera.importers` is forbidden from importing SQLAlchemy
at all — which is what lets a whole file be checked before a single row is committed, and
what makes a dry run identical to the real thing minus the commit.

Two jobs, and they are worth keeping apart:

* **Resolving references.** A spreadsheet says `Block A`, not `3`. Names are matched
  against what the project already holds, and a miss is reported with the nearest thing
  that does exist — *did you mean 'projector'?* — but never applied. An importer that
  silently corrects `projecter` will one day silently merge two different rooms, and
  nobody will be able to say which import did it.
* **Validating a row.** Not repeated here. The domain already knows a capacity cannot be
  negative and a course needs a code, so each row is offered to the domain object it
  claims to be, and whatever it says is turned into a problem against that row.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

from tessera.domain import entities as d
from tessera.domain import groups as dg
from tessera.domain.ids import (
    BuildingId,
    DepartmentId,
    FeatureId,
    ProgramId,
    StudentGroupId,
)
from tessera.importers.detect import Kind
from tessera.importers.sheet import Row, Sheet


@dataclass(frozen=True)
class Problem:
    """One reason one row cannot be imported, in the terms the user typed."""

    row: int
    column: str
    message: str
    suggestion: str = ""


@dataclass(frozen=True)
class Catalogue:
    """What the project already contains, by name.

    Passed in rather than looked up, because this module cannot reach a database and
    should not want to. It is assembled by the layer that can — which also means the same
    plan can be built against a hypothetical project in a test with no engine running.

    Lookups are case-insensitive and space-insensitive: nobody types `Block A` the same
    way twice across two hundred rows.
    """

    buildings: Mapping[str, int] = field(default_factory=dict)
    features: Mapping[str, int] = field(default_factory=dict)
    departments: Mapping[str, int] = field(default_factory=dict)
    programs: Mapping[str, int] = field(default_factory=dict)
    groups: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Prepared:
    """A row that would be written, and where it came from."""

    row: int
    entity: d.Room | d.Instructor | d.Course | dg.StudentGroup
    #: A parent named in *this file* rather than already in the project.
    #:
    #: A sheet of groups almost always contains an intake and the batches beneath it, so
    #: resolving parents only against what already exists would reject every child in the
    #: commonest file there is. The name is carried instead, and whoever writes the plan
    #: creates parents first and resolves it then.
    pending_parent: str = ""


@dataclass(frozen=True)
class Plan:
    kind: Kind
    mapping: dict[str, str]
    rows_total: int
    ready: tuple[Prepared, ...]
    problems: tuple[Problem, ...]

    @property
    def rows_ready(self) -> int:
        return len(self.ready)


def _folded(known: Mapping[str, int]) -> dict[str, int]:
    return {_fold(name): value for name, value in known.items()}


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def _resolve(value: str, known: Mapping[str, int]) -> tuple[int | None, str]:
    """A name to an id, or nothing and the nearest thing that exists."""
    folded = _folded(known)
    found = folded.get(_fold(value))
    if found is not None:
        return found, ""
    close = get_close_matches(_fold(value), list(folded), n=1, cutoff=0.7)
    original = next((n for n in known if _fold(n) == close[0]), "") if close else ""
    return None, original


def _number(value: str) -> int | None:
    """An integer, or nothing. `forty` stays `forty` for the message to quote."""
    try:
        return int(value)
    except ValueError:
        return None


def _columns_for(mapping: Mapping[str, str], name: str) -> list[str]:
    return [column for column, target in mapping.items() if target == name]


def _value(row: Row, mapping: Mapping[str, str], name: str) -> str:
    for column in _columns_for(mapping, name):
        if row.get(column):
            return row.get(column)
    return ""


def _values(row: Row, mapping: Mapping[str, str], name: str) -> list[str]:
    """Every non-empty value feeding a repeatable field.

    A sheet may spread equipment across `Equipment 1`, `Equipment 2`, or pack it into one
    cell as `projector, computers`. Both are common and neither is wrong.
    """
    found: list[str] = []
    for column in _columns_for(mapping, name):
        for part in row.get(column).replace(";", ",").split(","):
            if part.strip():
                found.append(part.strip())
    return found


def _names_in(sheet: Sheet, mapping: Mapping[str, str]) -> set[str]:
    """Every name this file itself defines, folded for comparison.

    What makes an in-file parent distinguishable from a typo: `2024 Intake` on row 2 is a
    group that will exist by the time row 3 is written, and `2025 Intake` is not.
    """
    return {
        _fold(_value(row, mapping, "name")) for row in sheet.rows if _value(row, mapping, "name")
    }


def build(sheet: Sheet, kind: Kind, mapping: Mapping[str, str], known: Catalogue) -> Plan:
    """Everything the file would add, and everything wrong with it."""
    problems: list[Problem] = []
    ready: list[Prepared] = []

    for header in sheet.duplicate_headers:
        problems.append(
            Problem(
                row=1,
                column=header,
                message=f"{header!r} appears more than once; only the first is used.",
            )
        )

    builder = _BUILDERS[kind]
    defined = _names_in(sheet, mapping)
    counted = 0
    for row in sheet.rows:
        if not any(row.cells.values()):
            continue  # a blank line between blocks is formatting, not a missing record
        counted += 1
        entity, pending, row_problems = builder(row, mapping, known, defined)
        problems.extend(row_problems)
        if entity is not None:
            ready.append(Prepared(row=row.number, entity=entity, pending_parent=pending))

    return Plan(
        kind=kind,
        mapping=dict(mapping),
        rows_total=counted,
        ready=tuple(ready),
        problems=tuple(problems),
    )


def _domain(
    row: Row, build_entity: Any, column: str = "", pending: str = ""
) -> tuple[Any | None, str, list[Problem]]:
    """Hand the row to the domain and turn its objection into a row problem.

    The rules are not restated here. A capacity below zero, a course with no code and a
    group of the wrong kind are all already refused by the objects themselves, and a
    second copy of those rules in the importer is a second copy to keep in step.
    """
    try:
        return build_entity(), pending, []
    except ValueError as error:
        return None, "", [Problem(row=row.number, column=column, message=_first_message(error))]


def _first_message(error: ValueError) -> str:
    errors = getattr(error, "errors", None)
    if callable(errors):
        found = errors()
        if found:
            return str(found[0].get("msg", "")).removeprefix("Value error, ")
    return str(error)


def _room(
    row: Row, mapping: Mapping[str, str], known: Catalogue, defined: set[str]
) -> tuple[d.Room | None, str, list[Problem]]:
    problems: list[Problem] = []
    name = _value(row, mapping, "name")
    if not name:
        problems.append(Problem(row.number, "name", "A room needs a name."))

    raw_capacity = _value(row, mapping, "capacity")
    capacity = _number(raw_capacity)
    if capacity is None:
        problems.append(
            Problem(row.number, "capacity", f"{raw_capacity!r} is not a number of seats.")
        )

    building_id = None
    building = _value(row, mapping, "building")
    if building:
        building_id, near = _resolve(building, known.buildings)
        if building_id is None:
            problems.append(
                Problem(row.number, "building", f"No building called {building!r}.", near)
            )

    feature_ids: list[int] = []
    for wanted in _values(row, mapping, "features"):
        found, near = _resolve(wanted, known.features)
        if found is None:
            problems.append(
                Problem(row.number, "features", f"No equipment called {wanted!r}.", near)
            )
        else:
            feature_ids.append(found)

    if problems:
        return None, "", problems
    return _domain(
        row,
        lambda: d.Room(
            name=name,
            capacity=capacity or 0,
            building_id=BuildingId(building_id) if building_id is not None else None,
            features=frozenset(FeatureId(f) for f in feature_ids),
        ),
        "capacity",
    )


def _instructor(
    row: Row, mapping: Mapping[str, str], known: Catalogue, defined: set[str]
) -> tuple[d.Instructor | None, str, list[Problem]]:
    problems: list[Problem] = []
    name = _value(row, mapping, "name")
    if not name:
        problems.append(Problem(row.number, "name", "An instructor needs a name."))

    department_id = None
    department = _value(row, mapping, "department")
    if department:
        department_id, near = _resolve(department, known.departments)
        if department_id is None:
            problems.append(
                Problem(row.number, "department", f"No department called {department!r}.", near)
            )

    if problems:
        return None, "", problems
    return _domain(
        row,
        lambda: d.Instructor(
            name=name,
            email=_value(row, mapping, "email"),
            department_id=DepartmentId(department_id) if department_id is not None else None,
        ),
        "name",
    )


def _course(
    row: Row, mapping: Mapping[str, str], known: Catalogue, defined: set[str]
) -> tuple[d.Course | None, str, list[Problem]]:
    problems: list[Problem] = []
    code = _value(row, mapping, "code")
    name = _value(row, mapping, "name")
    if not code:
        problems.append(Problem(row.number, "code", "A course needs a code."))
    if not name:
        problems.append(Problem(row.number, "name", "A course needs a name."))

    raw_credits = _value(row, mapping, "credits")
    credits = _number(raw_credits) if raw_credits else 0
    if raw_credits and credits is None:
        problems.append(Problem(row.number, "credits", f"{raw_credits!r} is not a number."))

    department_id = None
    department = _value(row, mapping, "department")
    if department:
        department_id, near = _resolve(department, known.departments)
        if department_id is None:
            problems.append(
                Problem(row.number, "department", f"No department called {department!r}.", near)
            )

    if problems:
        return None, "", problems
    return _domain(
        row,
        lambda: d.Course(
            code=code,
            name=name,
            credits=credits or 0,
            department_id=DepartmentId(department_id) if department_id is not None else None,
        ),
        "credits",
    )


def _group(
    row: Row, mapping: Mapping[str, str], known: Catalogue, defined: set[str]
) -> tuple[dg.StudentGroup | None, str, list[Problem]]:
    problems: list[Problem] = []
    name = _value(row, mapping, "name")
    if not name:
        problems.append(Problem(row.number, "name", "A group needs a name."))

    raw_size = _value(row, mapping, "size")
    size = _number(raw_size) if raw_size else 0
    if raw_size and size is None:
        problems.append(Problem(row.number, "size", f"{raw_size!r} is not a number of students."))

    parent_id = None
    pending = ""
    parent = _value(row, mapping, "parent")
    if parent:
        parent_id, near = _resolve(parent, known.groups)
        if parent_id is None:
            if _fold(parent) in defined:
                # The parent is another row of this same file — an intake above its lab
                # batches, which is what a group sheet almost always looks like. Rejecting
                # it would reject every child in the commonest file there is.
                pending = parent
            else:
                problems.append(Problem(row.number, "parent", f"No group called {parent!r}.", near))

    program_id = None
    program = _value(row, mapping, "program")
    if program:
        program_id, near = _resolve(program, known.programs)
        if program_id is None:
            problems.append(
                Problem(row.number, "program", f"No programme called {program!r}.", near)
            )

    if problems:
        return None, "", problems
    return _domain(
        row,
        lambda: dg.StudentGroup(
            name=name,
            kind=dg.GroupKind.STRUCTURAL,
            size=size or 0,
            parent_id=StudentGroupId(parent_id) if parent_id is not None else None,
            program_id=ProgramId(program_id) if program_id is not None else None,
        ),
        "size",
        pending,
    )


_BUILDERS = {
    Kind.ROOMS: _room,
    Kind.INSTRUCTORS: _instructor,
    Kind.COURSES: _course,
    Kind.GROUPS: _group,
}
