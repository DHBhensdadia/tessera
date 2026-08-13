"""Programmes and student groups.

The interesting rules — cycles, dangling references, leaf resolution, who conflicts with
whom — are **not here**. They live in `tessera.domain.groups`, and this module reaches
them by building a `GroupSet` and letting it object.

That is deliberate and is the whole shape of this phase. The obvious alternative is a
recursive CTE to detect cycles in SQL, which would be a second implementation of the
rules, in a second language, obliged to agree with the first forever. Constructing the
prospective set costs O(groups) per write — hundreds of rows — and buys one place where
a conflict is defined.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain import groups as dg
from tessera.domain.ids import StudentGroupId
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError
from tessera.repository.structure import _get_or_404, _reject_duplicate, _rename

# --------------------------------------------------------------------------------
# programmes
# --------------------------------------------------------------------------------


def list_programs(session: DbSession, *, department_id: int | None = None) -> list[d.Program]:
    query = select(m.Program).order_by(m.Program.name)
    if department_id is not None:
        query = query.where(m.Program.department_id == department_id)
    return [mappers.program_to_domain(row) for row in session.scalars(query)]


def create_program(
    session: DbSession, *, name: str, code: str = "", department_id: int | None = None
) -> d.Program:
    if department_id is not None:
        _get_or_404(session, m.Department, department_id)
    _reject_duplicate(
        session,
        m.Program,
        name,
        scope_column=m.Program.department_id,
        scope_value=department_id,
    )
    row = m.Program(department_id=department_id, name=name, code=code)
    session.add(row)
    session.flush()
    return mappers.program_to_domain(row)


def get_program(session: DbSession, program_id: int) -> d.Program:
    return mappers.program_to_domain(_get_or_404(session, m.Program, program_id))


def update_program(session: DbSession, program_id: int, *, changes: Mapping[str, Any]) -> d.Program:
    """Rename a programme, or set its code.

    Its department is not editable: moving a programme would take its whole group tree
    to another department, which is the re-parenting hazard Decision #51 refuses in the
    equivalent case.
    """
    return mappers.program_to_domain(
        _rename(
            session, m.Program, program_id, changes=changes, scope_column=m.Program.department_id
        )
    )


def delete_program(session: DbSession, program_id: int) -> None:
    """Refuse while groups still belong to it.

    `student_group.program_id` is ON DELETE SET NULL, so the groups would survive as
    orphans rather than vanish — but an intake with no programme is meaningless, and
    silently producing a pile of them is worse than making the caller detach them first.
    """
    row = _get_or_404(session, m.Program, program_id)
    attached = session.scalar(
        select(func.count())
        .select_from(m.StudentGroup)
        .where(m.StudentGroup.program_id == program_id)
    )
    if attached:
        raise ConflictError(
            f"{row.name} still has student groups and cannot be deleted",
            blockers={"student_groups": int(attached)},
        )
    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------------
# groups — every write is validated by the domain
# --------------------------------------------------------------------------------


def _load_all(session: DbSession) -> list[dg.StudentGroup]:
    return [
        mappers.group_to_domain(row)
        for row in session.scalars(select(m.StudentGroup).order_by(m.StudentGroup.id))
    ]


def _group(**fields: Any) -> dg.StudentGroup:
    """One group, with its own rules enforced as a conflict rather than a crash.

    `StudentGroup` rejects a structural group carrying `member_ids`, because members are
    how a *cohort* names what it draws from and a tree node takes its students through
    its parent. Pydantic raises `ValidationError` for that — a `ValueError` subclass, but
    not a `RepositoryError`, so it escaped every caller and became a 500.
    """
    try:
        return dg.StudentGroup(**fields)
    except ValueError as error:
        raise ConflictError(_first_message(error)) from error


def _first_message(error: ValueError) -> str:
    """Pydantic's own text, without the type and documentation link around it.

    `str(ValidationError)` is four lines of machine detail. What a person needs is the
    sentence the domain wrote.
    """
    errors = getattr(error, "errors", None)
    if callable(errors):
        found = errors()
        if found:
            return str(found[0].get("msg", "")).removeprefix("Value error, ")
    return str(error)


def _validated(groups: Sequence[dg.StudentGroup]) -> dg.GroupSet:
    """Hand the prospective world to the domain and let it object.

    Everything it rejects — cycles, unknown parents, a cohort drawing from another
    cohort — becomes a 409 rather than an unhandled error, because in every case the
    request is coherent and the resulting *state* would not be.
    """
    try:
        return dg.GroupSet(list(groups))
    except ValueError as error:
        raise ConflictError(str(error)) from error


def group_set(session: DbSession) -> dg.GroupSet:
    """The resolved hierarchy: what the solver and the tree view both read."""
    return _validated(_load_all(session))


def list_groups(session: DbSession, *, program_id: int | None = None) -> list[dg.StudentGroup]:
    query = select(m.StudentGroup).order_by(m.StudentGroup.name)
    if program_id is not None:
        query = query.where(m.StudentGroup.program_id == program_id)
    return [mappers.group_to_domain(row) for row in session.scalars(query)]


def get_group(session: DbSession, group_id: int) -> dg.StudentGroup:
    return mappers.group_to_domain(_get_or_404(session, m.StudentGroup, group_id))


def create_group(
    session: DbSession,
    *,
    name: str,
    kind: dg.GroupKind = dg.GroupKind.STRUCTURAL,
    size: int = 0,
    program_id: int | None = None,
    parent_id: int | None = None,
    member_ids: Sequence[int] = (),
) -> dg.StudentGroup:
    if program_id is not None:
        _get_or_404(session, m.Program, program_id)
    _reject_duplicate(
        session,
        m.StudentGroup,
        name,
        scope_column=m.StudentGroup.parent_id,
        scope_value=parent_id,
    )

    # Built through `_group` rather than directly, because `StudentGroup` has rules of
    # its own — a structural group may not carry `member_ids` — and constructing it here
    # raw let pydantic's ValidationError escape the repository entirely. The API answered
    # that with a 500 until the console reached the same rule through a form and made it
    # visible. Every path out of this module is a RepositoryError.
    candidate = _group(
        id=StudentGroupId(-1),  # placeholder: the set only needs an id to be present
        name=name,
        kind=kind,
        size=size,
        parent_id=StudentGroupId(parent_id) if parent_id is not None else None,
        member_ids=frozenset(StudentGroupId(i) for i in member_ids),
    )
    # Validate before writing. A cycle or a bad reference should never reach the table,
    # and rolling one back afterwards would leave the id sequence to explain.
    _validated([*_load_all(session), candidate])

    row = m.StudentGroup(
        program_id=program_id,
        name=name,
        kind=kind.value,
        size=size,
        parent_id=parent_id,
    )
    if member_ids:
        row.members = _members(session, member_ids)
    session.add(row)
    session.flush()
    return mappers.group_to_domain(row)


def _members(session: DbSession, member_ids: Sequence[int]) -> list[m.StudentGroup]:
    wanted = {int(i) for i in member_ids}
    found = list(session.scalars(select(m.StudentGroup).where(m.StudentGroup.id.in_(wanted))))
    if missing := wanted - {row.id for row in found}:
        raise InvalidReferenceError("member_ids", list(missing))
    return found


def update_group(
    session: DbSession, group_id: int, *, changes: Mapping[str, Any]
) -> dg.StudentGroup:
    """Apply what was sent, then let the domain rule on the result.

    Re-parenting is the dangerous edit: pointing a group at its own descendant would
    make leaf resolution loop forever. The check is not written here — the prospective
    set is built with the change applied and `GroupSet` refuses it.
    """
    row = _get_or_404(session, m.StudentGroup, group_id)

    if "name" in changes:
        _reject_duplicate(
            session,
            m.StudentGroup,
            str(changes["name"]),
            scope_column=m.StudentGroup.parent_id,
            scope_value=changes.get("parent_id", row.parent_id),
            exclude_id=group_id,
        )

    prospective = {g.id: g for g in _load_all(session) if g.id is not None}
    current = prospective[StudentGroupId(group_id)]
    # Rebuilt through `_group` rather than `model_copy`, which does not re-validate:
    # copying a structural group and adding `member_ids` to it produced an object the
    # domain would have refused had anyone asked, and nobody was asking.
    prospective[StudentGroupId(group_id)] = _group(
        id=current.id,
        name=changes.get("name", current.name),
        kind=current.kind,
        size=changes.get("size", current.size),
        program_id=current.program_id,
        parent_id=(
            StudentGroupId(changes["parent_id"])
            if changes.get("parent_id") is not None
            else (None if "parent_id" in changes else current.parent_id)
        ),
        member_ids=(
            frozenset(StudentGroupId(i) for i in changes["member_ids"])
            if changes.get("member_ids") is not None
            else current.member_ids
        ),
    )
    _validated(list(prospective.values()))

    for field in ("name", "size"):
        if field in changes:
            setattr(row, field, changes[field])
    if "parent_id" in changes:
        row.parent_id = changes["parent_id"]
    if "program_id" in changes:
        if changes["program_id"] is not None:
            _get_or_404(session, m.Program, int(changes["program_id"]))
        row.program_id = changes["program_id"]
    if changes.get("member_ids") is not None:
        row.members = _members(session, changes["member_ids"])

    session.flush()
    return mappers.group_to_domain(row)


def delete_group(session: DbSession, group_id: int) -> None:
    """Refuse while anything still hangs off it.

    `parent_id` is ON DELETE CASCADE, so without this a mis-click on an intake would
    silently take its lab sub-batches with it, and one on a programme root would take
    the entire tree. The cascade stays as a backstop for paths that bypass this module,
    where its job is preventing dangling rows rather than performing the deletion.
    """
    row = _get_or_404(session, m.StudentGroup, group_id)

    children = session.scalar(
        select(func.count()).select_from(m.StudentGroup).where(m.StudentGroup.parent_id == group_id)
    )
    cohorts = session.scalar(
        select(func.count())
        .select_from(m.group_member)
        .where(m.group_member.c.member_id == group_id)
    )
    attending = session.scalar(
        select(func.count())
        .select_from(m.session_attendee)
        .where(m.session_attendee.c.group_id == group_id)
    )

    blockers = {
        "sub_groups": int(children or 0),
        "cohorts": int(cohorts or 0),
        "sessions": int(attending or 0),
    }
    if any(blockers.values()):
        raise ConflictError(
            f"{row.name} still has dependants and cannot be deleted",
            blockers={k: v for k, v in blockers.items() if v},
        )

    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------------
# views derived from the domain
# --------------------------------------------------------------------------------


def conflicts_of(session: DbSession, group_id: int) -> list[StudentGroupId]:
    """Groups sharing students with this one, so never taught opposite it.

    Answered by the domain, not by a query. The solver reads the same relation from the
    same place, which is the point.
    """
    groups = group_set(session)
    gid = StudentGroupId(group_id)
    if gid not in groups:
        raise NotFoundError("student_group", group_id)
    return sorted(peer for peer in groups.conflict_map[gid] if peer != gid)
