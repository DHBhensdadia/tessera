"""The rules a term is solved against, and the sliders that weigh them.

R1 §3 made the argument for storing these as data rather than as code: institutions
genuinely disagree about how gaps, room stability and staff convenience should trade off,
and exposing the weights *"turns 'your algorithm is wrong' into 'move this slider'"*. A
page is what makes that true — an API-only constraint layer is a preference nobody can
express an opinion about.

Every sentence on the page comes from the constraint's own spec rather than from this
module, so the rule and its description cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.api.targets import sentence as _sentence
from tessera.api.targets import target_names as _names
from tessera.domain.constraints import SPECS, ConstraintKind, ConstraintTarget
from tessera.domain.constraints import TargetKind as Kind
from tessera.repository import calendar as calendar_repo
from tessera.repository import constraints as repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class Choice:
    """One thing a constraint could be attached to, as the form offers it."""

    value: str
    label: str


@dataclass(frozen=True)
class Rule:
    """One stored constraint, resolved to what a reader needs to see."""

    id: int
    kind: str
    sentence: str
    weight: int
    is_hard: bool
    enabled: bool
    can_be_hard: bool
    params: dict[str, int]


def _rules(db: Db, term_id: int, names: dict[Kind, dict[int, str]]) -> list[Rule]:
    return [
        Rule(
            id=int(item.id or 0),
            kind=item.kind.value,
            sentence=_sentence(item, names),
            weight=item.weight,
            is_hard=item.is_hard,
            enabled=item.enabled,
            can_be_hard=bool(item.targets),
            params=dict(item.params),
        )
        for item in repo.list_constraints(db, term_id)
    ]


def _render(
    request: Request, db: Db, term_id: int | None, *, problem: str | None = None
) -> HTMLResponse:
    terms = calendar_repo.list_terms(db)
    chosen = term_id or (int(terms[0].id or 0) if terms else None)
    names = _names(db)

    return page(
        request,
        "rules/list.html",
        terms=terms,
        term_id=chosen,
        rules=_rules(db, chosen, names) if chosen else [],
        kinds=[
            Choice(value=kind.value, label=SPECS[kind].describe({}, "…"))
            for kind in ConstraintKind
            if SPECS[kind].targets != {Kind.SESSION}
        ],
        targets=[
            Choice(value=f"{kind.value}:{identifier}", label=f"{name} ({kind.value})")
            for kind, entries in names.items()
            for identifier, name in sorted(entries.items(), key=lambda pair: pair[1])
        ],
        problem=problem,
    )


@router.get("/constraints", include_in_schema=False)
def constraints(request: Request, db: Db, term_id: int | None = None) -> HTMLResponse:
    """The rules for one term.

    Session-level distribution rules are deliberately not offered here. They are written
    against specific sessions, which are generated rather than authored, so choosing them
    from a flat list of several hundred would be worse than useless — that belongs to the
    timetable view in Stage 5, where a session is something you can point at.
    """
    return _render(request, db, term_id)


@router.post("/constraints", include_in_schema=False)
def add_constraint(
    request: Request,
    db: Db,
    term_id: int = Form(...),
    kind: str = Form(...),
    target: list[str] | None = Form(None),
    slots: int | None = Form(None),
    days: int | None = Form(None),
    is_hard: bool = Form(False),
) -> Response:
    chosen = ConstraintKind(kind)
    params = {
        name: value
        for name, value in (("slots", slots), ("days", days))
        if name in SPECS[chosen].params and value is not None
    }
    try:
        repo.create_constraint(
            db,
            term_id,
            kind=chosen,
            targets=[_target(value) for value in target or []],
            params=params,
            is_hard=is_hard,
        )
    except (RepositoryError, ValueError) as error:
        return _render(request, db, term_id, problem=describe(error))
    return redirect(f"/console/constraints?term_id={term_id}")


@router.post("/constraints/{constraint_id}", include_in_schema=False)
def retune(
    request: Request,
    db: Db,
    constraint_id: int,
    term_id: int = Form(...),
    weight: int = Form(...),
    enabled: bool = Form(False),
) -> Response:
    """Where the slider writes to. One rule per submission, so a typo costs one rule."""
    try:
        repo.update_constraint(db, constraint_id, changes={"weight": weight, "enabled": enabled})
    except (RepositoryError, ValueError) as error:
        return _render(request, db, term_id, problem=describe(error))
    return redirect(f"/console/constraints?term_id={term_id}")


@router.post("/constraints/{constraint_id}/delete", include_in_schema=False)
def remove(request: Request, db: Db, constraint_id: int, term_id: int = Form(...)) -> Response:
    try:
        repo.delete_constraint(db, constraint_id)
    except RepositoryError as error:
        return _render(request, db, term_id, problem=describe(error))
    return redirect(f"/console/constraints?term_id={term_id}")


def _target(value: str) -> ConstraintTarget:
    kind, _, identifier = value.partition(":")
    return ConstraintTarget(kind=Kind(kind), id=int(identifier))
