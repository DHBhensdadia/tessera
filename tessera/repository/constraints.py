"""Storing the rules an institution chose, as opposed to the rules that are simply true.

Nothing here evaluates anything. A constraint is a row describing a preference or a
distribution rule; whether a given timetable satisfies it is Phase 4.1's question, asked
of a validator written as an independent reading of the same rules.

Every check in this module is a check the *domain* makes — the repository builds the
domain object and lets it object, so "at most 0 hours in a row" is refused in the one
place that rule lives (ADR-0004). What the repository adds is the two things the domain
cannot see: that the term exists, and that a target names a row that exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from tessera.domain.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintTarget,
    TargetKind,
    default_constraints,
)
from tessera.domain.ids import TermId
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import (
    InvalidReferenceError,
    RuleViolationError,
    first_message,
)
from tessera.repository.structure import _get_or_404


def list_constraints(
    session: DbSession, term_id: int, *, kind: ConstraintKind | None = None
) -> list[Constraint]:
    """Ordered by kind then id, so a reloaded page does not reshuffle itself."""
    _get_or_404(session, m.Term, term_id)
    query = (
        select(m.Constraint)
        .where(m.Constraint.term_id == term_id)
        .order_by(m.Constraint.kind, m.Constraint.id)
    )
    if kind is not None:
        query = query.where(m.Constraint.kind == kind.value)
    return [mappers.constraint_to_domain(row) for row in session.scalars(query)]


def get_constraint(session: DbSession, constraint_id: int) -> Constraint:
    return mappers.constraint_to_domain(_get_or_404(session, m.Constraint, constraint_id))


def create_constraint(
    session: DbSession,
    term_id: int,
    *,
    kind: ConstraintKind,
    is_hard: bool = False,
    weight: int = 1,
    targets: Iterable[ConstraintTarget] = (),
    params: Mapping[str, int] | None = None,
    enabled: bool = True,
) -> Constraint:
    _get_or_404(session, m.Term, term_id)
    item = _rule(
        term_id=TermId(term_id),
        kind=kind,
        is_hard=is_hard,
        weight=weight,
        targets=frozenset(targets),
        params=dict(params or {}),
        enabled=enabled,
    )
    # Before the mapper, which raises LookupError — an internal signal, not something
    # the API could turn into a field-level 422.
    _check_targets_exist(session, item.targets)
    _reject_targets_from_another_term(session, term_id, item.targets)

    row = mappers.constraint_to_orm(session, item)
    session.add(row)
    session.flush()
    return mappers.constraint_to_domain(row)


def update_constraint(
    session: DbSession, constraint_id: int, *, changes: Mapping[str, Any]
) -> Constraint:
    """Apply only the fields the caller sent, and re-validate the whole rule.

    Rebuilt through the domain rather than assigned field by field. Every field here
    interacts with another — dropping the targets from a hard preference makes it a
    term-wide rule that cannot be hard, and changing the kind changes which parameters
    are required — so a partial edit has to be checked as a whole or it is not checked.
    """
    row = _get_or_404(session, m.Constraint, constraint_id)
    current = mappers.constraint_to_domain(row)

    updated = _rule(
        id=current.id,
        term_id=current.term_id,
        kind=ConstraintKind(changes.get("kind", current.kind)),
        is_hard=bool(changes.get("is_hard", current.is_hard)),
        weight=int(changes.get("weight", current.weight)),
        targets=frozenset(changes.get("targets", current.targets)),
        params=dict(changes.get("params", current.params)),
        enabled=bool(changes.get("enabled", current.enabled)),
    )
    _reject_targets_from_another_term(session, row.term_id, updated.targets)

    row.kind = updated.kind.value
    row.is_hard = updated.is_hard
    row.weight = updated.weight
    row.params = dict(updated.params)
    row.enabled = updated.enabled
    if "targets" in changes:
        _check_targets_exist(session, updated.targets)
        row.targets = [
            m.ConstraintTarget(target_kind=t.kind.value, target_id=t.id)
            for t in sorted(updated.targets, key=lambda t: (t.kind.value, t.id))
        ]
    session.flush()
    return mappers.constraint_to_domain(row)


def delete_constraint(session: DbSession, constraint_id: int) -> None:
    """Always allowed. A rule is the institution's opinion, and opinions are withdrawn.

    Nothing depends on a constraint — a timetable records its penalty breakdown by kind,
    not by row — so there is no dependant to refuse for, unlike every other delete in
    this layer.
    """
    session.delete(_get_or_404(session, m.Constraint, constraint_id))
    session.flush()


def seed_default_constraints(session: DbSession, term_id: int) -> list[Constraint]:
    """The preference set a new term starts with.

    Called from ``create_term`` rather than from the API, so importing and (in 2.9)
    cloning get it too. Without this a new project has no preferences at all: the solver
    would have nothing to optimise and the weight sliders nothing to slide, which is how
    ``default_constraints`` sat unused from 1.3 to here.

    A cloned term copies whatever its parent had rather than being re-seeded — the point
    of cloning is to carry the tuning forward.
    """
    rows = [
        mappers.constraint_to_orm(session, item) for item in default_constraints(TermId(term_id))
    ]
    session.add_all(rows)
    session.flush()
    return [mappers.constraint_to_domain(row) for row in rows]


def _rule(**fields: Any) -> Constraint:
    """One constraint, with the domain's refusals turned into a 422 rather than a crash.

    Pydantic raises `ValidationError` — a `ValueError`, but not a `RepositoryError`, so
    without this it escapes every caller and becomes a 500. Exactly the fault Decision
    #68 fixed for student groups, and the same shape of fix: the domain stays the only
    place the rule lives, and the repository translates the refusal.
    """
    try:
        return Constraint(**fields)
    except ValueError as error:
        raise RuleViolationError(first_message(error)) from error


def _check_targets_exist(session: DbSession, targets: frozenset[ConstraintTarget]) -> None:
    by_kind: dict[TargetKind, set[int]] = {}
    for target in targets:
        by_kind.setdefault(target.kind, set()).add(target.id)

    for kind, ids in by_kind.items():
        model = mappers.TARGET_MODELS[kind]
        found = {row.id for row in session.scalars(select(model).where(model.id.in_(ids)))}
        if missing := ids - found:
            raise InvalidReferenceError(f"targets[{kind.value}]", sorted(missing))


def _reject_targets_from_another_term(
    session: DbSession, term_id: int, targets: frozenset[ConstraintTarget]
) -> None:
    """A constraint may only name sessions belonging to its own term.

    ``target_id`` has no foreign key and could not carry a composite one anyway, so
    nothing in the schema relates a target to the constraint's term. A rule over another
    term's sessions would be silently unsatisfiable — it would never match anything the
    solver placed, and would read as a constraint that simply does not work.

    Only sessions are term-scoped. Instructors, groups, rooms and courses outlive a term
    by design, which is what makes them reusable across one.
    """
    session_ids = {t.id for t in targets if t.kind is TargetKind.SESSION}
    if not session_ids:
        return

    foreign = sorted(
        session.scalars(
            select(m.Session.id).where(m.Session.id.in_(session_ids), m.Session.term_id != term_id)
        )
    )
    if foreign:
        raise RuleViolationError(f"sessions {foreign} belong to another term", field="targets")
