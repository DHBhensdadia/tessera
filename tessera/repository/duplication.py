"""Rolling a term forward into the next semester.

The feature that makes the application worth keeping. The first semester costs a day of
data entry; every one after it should cost an hour, and that is only true if what carries
over carries over *completely* — a duplicate that loses the tuned weights, or the Friday
afternoon somebody negotiated, is one the user stops trusting and stops using.

Two things here are less obvious than they look.

**Most of what P7's checklist offers cannot be copied, because it was never term-scoped.**
Rooms, instructors, student groups and courses hang off the institution, which is exactly
what makes them reusable across terms (R5 §2). The new term can see them the moment it
exists. So those flags describe a *guarantee* rather than an action, and unticking one
cannot remove anything — which is why this module answers with a receipt saying what it
actually did rather than echoing the request back.

**Sessions are expanded, never copied.** `expansion.expand` is the only definition of
which sessions a term has, and duplicating rows would be a second one obliged to agree
with it forever — the drift ADR-0004 and Decision #5 exist to prevent. Copy the templates
and run the expander, and "assignments cleared" is true by construction rather than by
remembering to delete something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain.constraints import ConstraintKind, ConstraintScope, TargetKind
from tessera.repository import calendar as calendar_repo
from tessera.repository import expansion
from tessera.repository import models as m
from tessera.repository.errors import RuleViolationError
from tessera.repository.structure import _get_or_404


class Carried(StrEnum):
    """What happened to one item on the checklist."""

    COPIED = "copied"
    SHARED = "shared"
    """Available to the new term without being copied, because it is not term-scoped.

    Reported rather than silently ignored: the user ticked a box, and telling them
    nothing happened when the *outcome* they wanted did happen would be as wrong as
    claiming a copy that never took place.
    """

    SKIPPED = "skipped"


@dataclass(frozen=True)
class Receipt:
    """What a duplication actually did, item by item.

    A receipt rather than an echo of the request. Four of the seven things the interface
    offers cannot be copied and cannot be withheld, so a response that repeated the flags
    back would be describing a different operation from the one that ran.
    """

    term: d.Term
    items: dict[str, Carried] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def copied(self) -> list[str]:
        return sorted(name for name, state in self.items.items() if state is Carried.COPIED)


#: The things that live above a term and are therefore available to it for free. Named
#: here so the receipt can say *why* nothing was copied rather than reporting a silence.
SHARED_BY_NATURE = ("rooms", "instructors", "groups", "courses")


def duplicate_term(
    session: DbSession,
    term_id: int,
    *,
    name: str,
    academic_year: str,
    copy_offerings: bool = True,
    copy_constraints: bool = True,
    copy_instructors: bool = True,
    copy_rooms: bool = True,
    copy_groups: bool = True,
    copy_courses: bool = True,
    copy_assignments: bool = False,
) -> Receipt:
    """Create the next term from this one, carrying what is genuinely its own.

    The new term is built through `create_term`, so every rule about names, grids and
    institutions applies — including the duplicate-name refusal, which is the common
    mistake here (duplicating Autumn into Autumn).

    `create_term` seeds the default preferences. When constraints are being carried the
    seeded ones are replaced by the originals, because carrying the tuning forward is the
    entire point and re-seeding would discard it while looking like it worked.
    """
    source = _get_or_404(session, m.Term, term_id)

    if copy_assignments and not copy_offerings:
        raise RuleViolationError(
            "assignments cannot be carried without the offerings they place",
            field="copy_offerings",
        )

    created = calendar_repo.create_term(
        session,
        institution_id=source.institution_id,
        time_grid_id=source.time_grid_id,
        academic_year=academic_year,
        name=name,
    )
    target_id = int(created.id or 0)

    receipt = Receipt(term=created)
    for shared, wanted in zip(
        SHARED_BY_NATURE, (copy_rooms, copy_instructors, copy_groups, copy_courses), strict=True
    ):
        receipt.items[shared] = Carried.SHARED if wanted else Carried.SKIPPED

    receipt.items["constraints"] = Carried.SKIPPED
    if copy_constraints:
        receipt.counts["constraints"] = _copy_constraints(session, term_id, target_id)
        receipt.items["constraints"] = Carried.COPIED

    receipt.items["availability"] = Carried.SKIPPED
    if copy_instructors or copy_rooms:
        receipt.counts["availability"] = _copy_availability(
            session, term_id, target_id, instructors=copy_instructors, rooms=copy_rooms
        )
        receipt.items["availability"] = Carried.COPIED

    receipt.items["offerings"] = Carried.SKIPPED
    if copy_offerings:
        offerings, sessions = _copy_offerings(session, term_id, target_id)
        receipt.counts["offerings"] = offerings
        receipt.counts["sessions"] = sessions
        receipt.items["offerings"] = Carried.COPIED

    # Assignments are the one thing the exit test insists must not come across, and the
    # default reflects that: a placement is a decision about *this* semester's calendar.
    receipt.items["assignments"] = Carried.SKIPPED
    session.flush()
    return receipt


def _copy_constraints(session: DbSession, source_id: int, target_id: int) -> int:
    """Move the tuned rules across, replacing the defaults the new term was seeded with.

    The seeded rows are deleted rather than merged. A term that carries its predecessor's
    preferences *and* a fresh set of defaults would have two of each, with different
    weights, and no way for the user to tell which one the solver read.
    """
    seeded = session.scalars(select(m.Constraint).where(m.Constraint.term_id == target_id)).all()
    for row in seeded:
        session.delete(row)
    session.flush()

    originals = session.scalars(select(m.Constraint).where(m.Constraint.term_id == source_id)).all()

    carried = 0
    for row in originals:
        # A rule about last term's *sessions* cannot come across: those rows belong to
        # the term being copied from, and the new term's sessions are different rows with
        # different ids. Rules about people, groups, rooms and courses carry over intact,
        # which is what a per-instructor limit needs.
        targets = [t for t in row.targets if t.target_kind != TargetKind.SESSION.value]

        # Dropping them can empty a rule that is meaningless without targets — "these two
        # must not overlap" naming nothing. Such a rule is skipped rather than written
        # empty, which the domain would refuse anyway, and rather than written with the
        # old ids, which would point it at another term's rows.
        if not targets and ConstraintKind(row.kind).scope is ConstraintScope.TARGETED:
            continue

        copy = m.Constraint(
            term_id=target_id,
            kind=row.kind,
            is_hard=row.is_hard,
            weight=row.weight,
            params=dict(row.params or {}),
            enabled=row.enabled,
        )
        copy.targets = [
            m.ConstraintTarget(target_kind=t.target_kind, target_id=t.target_id) for t in targets
        ]
        session.add(copy)
        carried += 1
    session.flush()
    return carried


def _copy_availability(
    session: DbSession, source_id: int, target_id: int, *, instructors: bool, rooms: bool
) -> int:
    """Carry the week people and rooms are not free, including its strength.

    `is_hard` and `weight` come across too. A soft "would rather not teach Friday
    afternoon" that arrived in the new term as a hard refusal would be a rule nobody
    wrote, and one they would have to find to remove.
    """
    rows = session.scalars(
        select(m.Unavailability).where(m.Unavailability.term_id == source_id)
    ).all()
    carried = [
        row
        for row in rows
        if (instructors and row.instructor_id is not None) or (rooms and row.room_id is not None)
    ]
    session.add_all(
        m.Unavailability(
            term_id=target_id,
            instructor_id=row.instructor_id,
            room_id=row.room_id,
            slot=row.slot,
            reason=row.reason,
            is_hard=row.is_hard,
            weight=row.weight,
        )
        for row in carried
    )
    session.flush()
    return len(carried)


def _copy_offerings(session: DbSession, source_id: int, target_id: int) -> tuple[int, int]:
    """Copy what is taught and how it is patterned, then let the expander make sessions.

    Returns the number of offerings copied and the number of sessions that came out.
    """
    offerings = session.scalars(select(m.Offering).where(m.Offering.term_id == source_id)).all()

    produced = 0
    for offering in offerings:
        copy = m.Offering(term_id=target_id, course_id=offering.course_id)
        session.add(copy)
        session.flush()

        templates = session.scalars(
            select(m.SessionTemplate).where(m.SessionTemplate.offering_id == offering.id)
        ).all()
        for template in templates:
            session.add(_copy_template(template, int(copy.id)))
        session.flush()

        produced += len(expansion.expand(session, int(copy.id)))
    return len(offerings), produced


def _copy_template(template: m.SessionTemplate, offering_id: int) -> m.SessionTemplate:
    copy = m.SessionTemplate(
        offering_id=offering_id,
        kind=template.kind,
        duration_slots=template.duration_slots,
        per_week=template.per_week,
        split_per_attendee=template.split_per_attendee,
        week_pattern=template.week_pattern,
    )
    copy.attendees = list(template.attendees)
    copy.instructors = list(template.instructors)
    copy.required_features = list(template.required_features)
    copy.set_feature_counts(template.feature_counts)
    return copy
