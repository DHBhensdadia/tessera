"""Reading and writing the things that outlive a term: institutions, departments,
buildings, features and rooms.

Functions rather than classes, taking a session and returning **domain** objects. The
session is passed in rather than owned here because the API opens one per request and
commits it once; a repository that managed its own would commit halfway through a
request that later fails.

This module sets the shape every other Stage 2 repository copies:

* one module per group of related entities
* a plain function per operation
* domain objects out, never ORM rows — an ORM row handed upward is a lazy-loading bug
  waiting for the session to close
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain.ids import BuildingId, FeatureId
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError

# --------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------


def _get_or_404[T: m.Base](session: DbSession, model: type[T], identifier: int) -> T:
    row = session.get(model, identifier)
    if row is None:
        raise NotFoundError(model.__tablename__, identifier)
    return row


def _check_exist(session: DbSession, model: type[m.Base], ids: set[int], field: str) -> None:
    """Reject references to records that do not exist.

    Without this the database would raise a foreign-key error whose message names a
    constraint rather than the field the caller sent, which is unhelpful at the point
    where it matters — a spreadsheet import naming a feature that was never created.
    """
    if not ids:
        return
    found = set(session.scalars(select(model.id).where(model.id.in_(ids))))
    if missing := ids - found:
        raise InvalidReferenceError(field, list(missing))


def _reject_duplicate(
    session: DbSession,
    model: type[m.Base],
    value: str,
    *,
    column: object | None = None,
    scope_column: object | None = None,
    scope_value: int | None = None,
    exclude_id: int | None = None,
) -> None:
    """Answer with a sentence rather than a constraint violation.

    The unique constraints in the schema are the real guarantee; this exists so the
    message says "a room called LH-201 already exists in this building" instead of
    quoting an index name. Check-then-act is a race in principle — in a single-user
    application it is not, and the constraint still catches it.

    ``column`` defaults to the model's ``name`` because that is what almost everything
    here is identified by. Courses are the exception — they are identified by ``code``,
    and two courses may legitimately share a name.

    One thing this catches that the database does not: when the scope is null, SQL
    treats each null as distinct and the unique constraint does not fire, whereas
    SQLAlchemy renders ``scope_column == None`` as ``IS NULL`` and this check *does*
    match. So a duplicate under an unassigned parent is refused here and only here.
    """
    target = column if column is not None else model.name  # type: ignore[attr-defined]
    query = select(model.id).where(target == value)  # type: ignore[arg-type]
    if scope_column is not None:
        query = query.where(scope_column == scope_value)  # type: ignore[arg-type]
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    if session.scalars(query).first() is None:
        return

    # "called" only reads correctly for a name. A course collides on its code, and
    # "a course called 'CS101'" invites the reader to go looking for a course of that
    # name, which is not what happened.
    field = str(getattr(target, "key", "name"))
    descriptor = "called" if field == "name" else f"with {field}"
    raise ConflictError(f"a {model.__tablename__} {descriptor} {value!r} already exists here")


# --------------------------------------------------------------------------------
# institutions, departments, buildings, features
# --------------------------------------------------------------------------------


def _rename[T: m.Base](
    session: DbSession,
    model: type[T],
    identifier: int,
    *,
    changes: Mapping[str, Any],
    scope_column: object | None = None,
) -> T:
    """Rename one of the "just a name" entities, and set its code if it has one.

    These five — institutions, departments, buildings, features, programmes — were given
    `list` and `create` by the 1.4 freeze and nothing else, so until 2.4b a mistyped name
    was permanent. They differ only in which uniqueness scope they sit in, which is the
    single argument here; five near-identical functions would differ in nothing else and
    drift the moment one of them was touched.

    `exclude_id` is what makes renaming a thing to its own name a no-op rather than a
    collision with itself — the bug found in 2.1 and worth not reintroducing five times.
    """
    row = _get_or_404(session, model, identifier)

    if "name" in changes and changes["name"] is not None:
        _reject_duplicate(
            session,
            model,
            str(changes["name"]),
            scope_column=scope_column,
            scope_value=getattr(row, str(getattr(scope_column, "key", "")), None)
            if scope_column is not None
            else None,
            exclude_id=identifier,
        )

    for field in ("name", "code"):
        if changes.get(field) is not None:
            setattr(row, field, changes[field])

    session.flush()
    return row


def _refuse_while_dependants[T: m.Base](
    session: DbSession, row: T, blockers: Mapping[str, int]
) -> None:
    present = {k: v for k, v in blockers.items() if v}
    if present:
        raise ConflictError(
            f"{getattr(row, 'name', 'this record')} still has dependants and cannot be deleted",
            blockers=present,
        )


def get_institution(session: DbSession, institution_id: int) -> d.Institution:
    return mappers.institution_to_domain(_get_or_404(session, m.Institution, institution_id))


def update_institution(
    session: DbSession, institution_id: int, *, changes: Mapping[str, Any]
) -> d.Institution:
    return mappers.institution_to_domain(
        _rename(session, m.Institution, institution_id, changes=changes)
    )


def delete_institution(session: DbSession, institution_id: int) -> None:
    """Refuse while anything at all belongs to it.

    An institution is the root of **five** `ON DELETE CASCADE` chains — buildings,
    departments, features, time grids and terms — and terms reach sessions and
    assignments beyond that. Without this, deleting one would empty an entire project
    from a single confirmation dialog.
    """
    row = _get_or_404(session, m.Institution, institution_id)
    _refuse_while_dependants(
        session,
        row,
        {
            "buildings": _count(session, m.Building, m.Building.institution_id, institution_id),
            "departments": _count(
                session, m.Department, m.Department.institution_id, institution_id
            ),
            "features": _count(session, m.Feature, m.Feature.institution_id, institution_id),
            "time_grids": _count(session, m.TimeGrid, m.TimeGrid.institution_id, institution_id),
            "terms": _count(session, m.Term, m.Term.institution_id, institution_id),
        },
    )
    session.delete(row)
    session.flush()


def _count(session: DbSession, model: type[m.Base], column: object, value: int) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(column == value))  # type: ignore[arg-type]
        or 0
    )


def get_department(session: DbSession, department_id: int) -> d.Department:
    return mappers.department_to_domain(_get_or_404(session, m.Department, department_id))


def update_department(
    session: DbSession, department_id: int, *, changes: Mapping[str, Any]
) -> d.Department:
    return mappers.department_to_domain(
        _rename(
            session,
            m.Department,
            department_id,
            changes=changes,
            scope_column=m.Department.institution_id,
        )
    )


def delete_department(session: DbSession, department_id: int) -> None:
    """Refuse while programmes belong to it — but **not** for courses.

    `program.department_id` cascades, so programmes and the group trees under them would
    go. `course.department_id` is `ON DELETE SET NULL`, and a course with no department is
    a state the catalogue is designed for: Decision #50 exists because a syllabus
    committee creates courses before ownership is settled. Blocking on courses would make
    that design unreachable.
    """
    row = _get_or_404(session, m.Department, department_id)
    _refuse_while_dependants(
        session,
        row,
        {"programs": _count(session, m.Program, m.Program.department_id, department_id)},
    )
    session.delete(row)
    session.flush()


def get_building(session: DbSession, building_id: int) -> d.Building:
    return mappers.building_to_domain(_get_or_404(session, m.Building, building_id))


def update_building(
    session: DbSession, building_id: int, *, changes: Mapping[str, Any]
) -> d.Building:
    return mappers.building_to_domain(
        _rename(
            session,
            m.Building,
            building_id,
            changes=changes,
            scope_column=m.Building.institution_id,
        )
    )


def get_feature(session: DbSession, feature_id: int) -> d.Feature:
    return mappers.feature_to_domain(_get_or_404(session, m.Feature, feature_id))


def update_feature(session: DbSession, feature_id: int, *, changes: Mapping[str, Any]) -> d.Feature:
    return mappers.feature_to_domain(
        _rename(
            session, m.Feature, feature_id, changes=changes, scope_column=m.Feature.institution_id
        )
    )


def list_institutions(session: DbSession) -> list[d.Institution]:
    rows = session.scalars(select(m.Institution).order_by(m.Institution.name))
    return [mappers.institution_to_domain(row) for row in rows]


def create_institution(session: DbSession, *, name: str) -> d.Institution:
    _reject_duplicate(session, m.Institution, name)
    row = m.Institution(name=name)
    session.add(row)
    session.flush()
    return mappers.institution_to_domain(row)


def list_departments(
    session: DbSession, *, institution_id: int | None = None
) -> list[d.Department]:
    query = select(m.Department).order_by(m.Department.name)
    if institution_id is not None:
        query = query.where(m.Department.institution_id == institution_id)
    return [mappers.department_to_domain(row) for row in session.scalars(query)]


def create_department(
    session: DbSession, *, institution_id: int, name: str, code: str = ""
) -> d.Department:
    _get_or_404(session, m.Institution, institution_id)
    _reject_duplicate(
        session,
        m.Department,
        name,
        scope_column=m.Department.institution_id,
        scope_value=institution_id,
    )
    row = m.Department(institution_id=institution_id, name=name, code=code)
    session.add(row)
    session.flush()
    return mappers.department_to_domain(row)


def list_buildings(session: DbSession, *, institution_id: int | None = None) -> list[d.Building]:
    query = select(m.Building).order_by(m.Building.name)
    if institution_id is not None:
        query = query.where(m.Building.institution_id == institution_id)
    return [mappers.building_to_domain(row) for row in session.scalars(query)]


def create_building(session: DbSession, *, institution_id: int, name: str) -> d.Building:
    _get_or_404(session, m.Institution, institution_id)
    _reject_duplicate(
        session,
        m.Building,
        name,
        scope_column=m.Building.institution_id,
        scope_value=institution_id,
    )
    row = m.Building(institution_id=institution_id, name=name)
    session.add(row)
    session.flush()
    return mappers.building_to_domain(row)


def list_features(session: DbSession, *, institution_id: int | None = None) -> list[d.Feature]:
    query = select(m.Feature).order_by(m.Feature.name)
    if institution_id is not None:
        query = query.where(m.Feature.institution_id == institution_id)
    return [mappers.feature_to_domain(row) for row in session.scalars(query)]


def create_feature(session: DbSession, *, institution_id: int, name: str) -> d.Feature:
    _get_or_404(session, m.Institution, institution_id)
    _reject_duplicate(
        session, m.Feature, name, scope_column=m.Feature.institution_id, scope_value=institution_id
    )
    row = m.Feature(institution_id=institution_id, name=name)
    session.add(row)
    session.flush()
    return mappers.feature_to_domain(row)


# --------------------------------------------------------------------------------
# rooms
# --------------------------------------------------------------------------------


def _room_query(
    *,
    building_id: int | None = None,
    min_capacity: int | None = None,
    required_features: Sequence[int] | None = None,
) -> Select[tuple[m.Room]]:
    """Rooms matching every filter given.

    The feature filter is the interesting one: it asks for rooms providing **at least**
    the named features, which is relational division and has no direct SQL operator.

    Written as a join restricted to the wanted features, grouped by room, keeping only
    rooms whose distinct match count equals how many were asked for. The alternative —
    one EXISTS subquery per feature — reads more plainly but grows the query with each
    feature; this stays one statement whether the caller asks for one or six.
    """
    query = select(m.Room)
    if building_id is not None:
        query = query.where(m.Room.building_id == building_id)
    if min_capacity is not None:
        query = query.where(m.Room.capacity >= min_capacity)

    wanted = list(required_features or ())
    if wanted:
        query = (
            query.join(m.room_feature, m.room_feature.c.room_id == m.Room.id)
            .where(m.room_feature.c.feature_id.in_(wanted))
            .group_by(m.Room.id)
            .having(func.count(func.distinct(m.room_feature.c.feature_id)) == len(set(wanted)))
        )
    return query.order_by(m.Room.name)


def list_rooms(
    session: DbSession,
    *,
    building_id: int | None = None,
    min_capacity: int | None = None,
    required_features: Sequence[int] | None = None,
) -> list[d.Room]:
    query = _room_query(
        building_id=building_id, min_capacity=min_capacity, required_features=required_features
    )
    return [mappers.room_to_domain(row) for row in session.scalars(query).unique()]


def get_room(session: DbSession, room_id: int) -> d.Room:
    return mappers.room_to_domain(_get_or_404(session, m.Room, room_id))


def create_room(
    session: DbSession,
    *,
    name: str,
    capacity: int,
    building_id: int | None = None,
    feature_ids: Sequence[int] = (),
) -> d.Room:
    if building_id is not None:
        _get_or_404(session, m.Building, building_id)
    _check_exist(session, m.Feature, set(feature_ids), "feature_ids")
    _reject_duplicate(
        session, m.Room, name, scope_column=m.Room.building_id, scope_value=building_id
    )

    row = mappers.room_to_orm(
        session,
        d.Room(
            name=name,
            capacity=capacity,
            building_id=BuildingId(building_id) if building_id is not None else None,
            features=frozenset(FeatureId(i) for i in feature_ids),
        ),
    )
    session.add(row)
    session.flush()
    return mappers.room_to_domain(row)


def update_room(
    session: DbSession,
    room_id: int,
    *,
    changes: Mapping[str, Any],
) -> d.Room:
    """Apply only the fields the caller actually sent.

    ``changes`` comes from ``model_dump(exclude_unset=True)``, which is what makes
    PATCH work: a field absent from the request is left alone, while a field explicitly
    set to null is cleared. A plain "is it None?" check cannot tell those apart.

    Typed as ``Any`` because it genuinely is: the values are whatever the caller sent,
    already validated against the wire schema before arriving here.
    """
    row = _get_or_404(session, m.Room, room_id)

    if "building_id" in changes:
        building_id = changes["building_id"]
        if building_id is not None:
            _get_or_404(session, m.Building, int(building_id))
        row.building_id = building_id

    if "name" in changes:
        _reject_duplicate(
            session,
            m.Room,
            str(changes["name"]),
            scope_column=m.Room.building_id,
            scope_value=row.building_id,
            exclude_id=room_id,
        )
        row.name = str(changes["name"])

    if "capacity" in changes:
        row.capacity = int(changes["capacity"])

    if "feature_ids" in changes:
        ids = {int(i) for i in changes["feature_ids"] or ()}
        _check_exist(session, m.Feature, ids, "feature_ids")
        row.features = list(session.scalars(select(m.Feature).where(m.Feature.id.in_(ids))))

    session.flush()
    return mappers.room_to_domain(row)


def delete_room(session: DbSession, room_id: int) -> None:
    """Refuse to delete a room that is still in use, and say what is using it.

    ``assignment.room_id`` is ON DELETE RESTRICT, so the database would refuse this
    anyway — but as a constraint violation naming an index. Counting first turns that
    into "used by 18 assignments", which is the difference between an error a user can
    act on and one they can only report.
    """
    row = _get_or_404(session, m.Room, room_id)

    assignments = session.scalar(
        select(func.count()).select_from(m.Assignment).where(m.Assignment.room_id == room_id)
    )
    if assignments:
        raise ConflictError(
            f"{row.name} is still scheduled and cannot be deleted",
            blockers={"assignments": int(assignments)},
        )

    session.delete(row)
    session.flush()


def rooms_that_can_host(
    session: DbSession, *, headcount: int, required_features: Sequence[int] = ()
) -> list[d.Room]:
    """Rooms big enough and equipped for a session.

    The same question the solver asks for every session before search begins, and the
    reason it lives here rather than being assembled by each caller: `Room.can_host`
    expresses the rule in the domain, and this is its SQL counterpart. They must agree,
    and a test checks that they do.
    """
    return list_rooms(session, min_capacity=headcount, required_features=required_features)


def delete_feature(session: DbSession, feature_id: int) -> None:
    row = _get_or_404(session, m.Feature, feature_id)
    rooms = session.scalar(
        select(func.count())
        .select_from(m.room_feature)
        .where(m.room_feature.c.feature_id == feature_id)
    )
    required = session.scalar(
        select(func.count())
        .select_from(m.session_feature)
        .where(m.session_feature.c.feature_id == feature_id)
    )
    if rooms or required:
        raise ConflictError(
            f"{row.name} is still in use and cannot be deleted",
            blockers={"rooms": int(rooms or 0), "sessions": int(required or 0)},
        )
    session.delete(row)
    session.flush()


def delete_building(session: DbSession, building_id: int) -> None:
    """Buildings may be deleted while rooms point at them.

    ``room.building_id`` is ON DELETE SET NULL, so the rooms survive unattached rather
    than disappearing with the building. Losing a hundred rooms because a building was
    renamed the wrong way would be a far worse outcome than a hundred rooms briefly
    lacking an address.
    """
    row = _get_or_404(session, m.Building, building_id)
    session.delete(row)
    session.flush()
