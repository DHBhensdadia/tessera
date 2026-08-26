"""Availability and constraints — everything that narrows what the solver may do."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from tessera.api.deps import Db
from tessera.api.errors import problem_responses
from tessera.api.schemas import (
    ConstraintCatalogue,
    ConstraintCreate,
    ConstraintRead,
    ConstraintUpdate,
    Page,
    TargetWire,
    UnavailabilityCreate,
    UnavailabilityRead,
)
from tessera.api.targets import Names, sentence, target_names
from tessera.domain import entities as d
from tessera.domain.constraints import Constraint, ConstraintTarget, TargetKind
from tessera.repository import constraints as constraints_repo
from tessera.repository import people as people_repo

router = APIRouter(prefix="/api/v1", tags=["rules"])
ERRORS = problem_responses(404, 422, 501)


@router.get(
    "/terms/{term_id}/unavailability",
    response_model=Page[UnavailabilityRead],
    responses=ERRORS,
)
def list_unavailability(
    term_id: int, db: Db, kind: str | None = None, subject_id: int | None = None
) -> Page[UnavailabilityRead]:
    items = [
        _unavailability(x)
        for x in people_repo.list_unavailability(db, term_id, kind=kind, subject_id=subject_id)
    ]
    return Page(items=items, total=len(items))


@router.post(
    "/terms/{term_id}/unavailability",
    response_model=Page[UnavailabilityRead],
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def add_unavailability(
    term_id: int, payload: UnavailabilityCreate, db: Db
) -> Page[UnavailabilityRead]:
    """Takes a list of slots rather than one.

    Availability is edited by dragging across a grid, so a single interaction produces
    a range; one request per slot would mean dozens per gesture.

    Blocking an already-blocked slot is a no-op rather than a conflict: dragging across
    a partly-blocked range is ordinary use.
    """
    rows = people_repo.block_slots(
        db,
        term_id,
        kind=payload.kind,
        subject_id=payload.subject_id,
        slots=payload.slots,
        reason=payload.reason,
        is_hard=payload.is_hard,
        weight=payload.weight,
    )
    items = [_unavailability(x) for x in rows]
    return Page(items=items, total=len(items))


@router.delete(
    "/terms/{term_id}/unavailability",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
)
def clear_unavailability(
    term_id: int,
    db: Db,
    kind: str,
    subject_id: int,
    slot: list[int] | None = Query(
        default=None,
        description="Repeat to free specific slots. Omit to clear the whole subject.",
    ),
) -> None:
    """Free slots again.

    Without `slot` this clears everything for the subject, which is what it always did.
    With it, only those slots are freed — which is what dragging across blocked cells to
    release them actually needs.
    """
    people_repo.unblock_slots(db, term_id, kind=kind, subject_id=subject_id, slots=slot)


@router.get("/constraint-catalogue", response_model=ConstraintCatalogue)
def constraint_catalogue() -> ConstraintCatalogue:
    """What a constraint may be, and what is true regardless.

    Not under `/constraints/…`, which would collide with `/constraints/{constraint_id}` and
    make the route order load-bearing — a literal path segment that only wins because it was
    declared first is the kind of thing somebody reorders in a tidy-up.

    Takes no project and reads no database: it is a property of the build, the same for every
    file this engine opens, which is why it has no term in its path and no 404 among its
    responses. A client can fetch it once per engine and keep it.
    """
    return ConstraintCatalogue.build()


@router.get("/terms/{term_id}/constraints", response_model=Page[ConstraintRead], responses=ERRORS)
def list_constraints(term_id: int, db: Db) -> Page[ConstraintRead]:
    # Names resolved once for the whole page, not once per rule.
    names = target_names(db, term_id=term_id)
    items = [_constraint(x, names) for x in constraints_repo.list_constraints(db, term_id)]
    return Page(items=items, total=len(items))


@router.post(
    "/terms/{term_id}/constraints",
    response_model=ConstraintRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def create_constraint(term_id: int, payload: ConstraintCreate, db: Db) -> ConstraintRead:
    return _constraint(
        constraints_repo.create_constraint(
            db,
            term_id,
            kind=payload.kind,
            is_hard=payload.is_hard,
            weight=payload.weight,
            targets=_targets(payload.targets, payload.target_ids),
            params=payload.params,
            enabled=payload.enabled,
        ),
        target_names(db, term_id=term_id),
    )


@router.patch("/constraints/{constraint_id}", response_model=ConstraintRead, responses=ERRORS)
def update_constraint(constraint_id: int, payload: ConstraintUpdate, db: Db) -> ConstraintRead:
    """Where the weight sliders write to.

    Different institutions genuinely disagree about how these should be balanced, so the
    argument is settled by the user rather than by us.
    """
    changes = payload.model_dump(exclude_unset=True)
    if "targets" in changes or "target_ids" in changes:
        changes["targets"] = _targets(payload.targets, payload.target_ids)
        changes.pop("target_ids", None)
    updated = constraints_repo.update_constraint(db, constraint_id, changes=changes)
    return _constraint(updated, target_names(db, term_id=int(updated.term_id or 0)))


@router.delete(
    "/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
def delete_constraint(constraint_id: int, db: Db) -> None:
    constraints_repo.delete_constraint(db, constraint_id)


def _targets(
    targets: list[TargetWire] | None, target_ids: list[int] | None
) -> list[ConstraintTarget]:
    """Whichever spelling the caller used. The schema has already refused both."""
    if targets:
        return [ConstraintTarget(kind=t.kind, id=t.id) for t in targets]
    return [ConstraintTarget(kind=TargetKind.SESSION, id=i) for i in target_ids or []]


def _constraint(item: Constraint, names: Names) -> ConstraintRead:
    """One constraint, with its targets named.

    `names` is required rather than optional. It was optional in spirit before — the
    summary fell back to `kind id` when nobody supplied them — and every response ever
    sent took that fallback, because the only caller that resolved names was the console,
    which renders its own sentence and never reads this one. Making it an argument is what
    stops the next endpoint from quietly doing the same.
    """
    return ConstraintRead(
        id=int(item.id or 0),
        term_id=int(item.term_id or 0),
        kind=item.kind,
        scope=item.kind.scope,
        is_hard=item.is_hard,
        weight=item.weight,
        target_ids=sorted(int(i) for i in item.target_ids),
        targets=[
            TargetWire(kind=t.kind, id=t.id)
            for t in sorted(item.targets, key=lambda t: (t.kind.value, t.id))
        ],
        params=dict(item.params),
        enabled=item.enabled,
        summary=sentence(item, names),
    )


def _unavailability(item: d.Unavailability) -> UnavailabilityRead:
    return UnavailabilityRead(
        kind=item.kind,
        subject_id=item.subject_id,
        slot=item.slot,
        reason=item.reason,
        is_hard=item.is_hard,
        weight=item.weight,
    )
