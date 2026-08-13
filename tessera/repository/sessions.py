"""Weekly patterns, and the teachable blocks they generate.

A **template** is what a timetabler authors: "three one-hour lectures to the whole
intake" is one, "one two-hour lab per sub-batch" is another. A **session** is what the
solver places. Expansion turns the first into the second and arrives in part 4.

Sessions are generated, never authored. The frozen contract has no ``POST /sessions``,
and P7 shows the weekly pattern generating them rather than anyone typing one in. That
shapes two things here:

* ``session.template_id`` is nullable only because ``ON DELETE SET NULL`` exists as a
  backstop. Through the API it is never null, and the functions below keep it that way.
* Editing a session is editing *generated* data. It is allowed — the domain calls a
  session "the scheduled reality" and the contract has ``PATCH /sessions/{id}`` — but
  only while nothing has been scheduled on top of it. See `update_session`.

The rules about what a template or session *is* — that it must be taught to someone,
how many sessions a pattern produces — are not here. They live in
`tessera.domain.entities`, and this module reaches them by constructing the domain
object and letting it object.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.domain.ids import StudentGroupId
from tessera.repository import groups as groups_repo
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError
from tessera.repository.structure import _check_exist, _get_or_404

# --------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------


def _validated[T](build: type[T], **fields: Any) -> T:
    """Construct a domain object, turning its complaints into conflicts.

    A template with no attendees is a coherent request producing an incoherent state,
    which is what a 409 is for. The rule itself lives in the domain and is not repeated
    here.
    """
    try:
        return build(**fields)
    except ValueError as error:
        raise ConflictError(str(error)) from error


def _scheduled_count(session: DbSession, session_ids: Sequence[int]) -> int:
    """How many of these sessions are placed in some timetable.

    "Scheduled" means an assignment references it. That is the state worth protecting:
    a session nobody has placed is bookkeeping, and one that is placed represents work
    somebody did.
    """
    if not session_ids:
        return 0
    return int(
        session.scalar(
            select(func.count())
            .select_from(m.Assignment)
            .where(m.Assignment.session_id.in_(list(session_ids)))
        )
        or 0
    )


def _institution_of_offering(session: DbSession, offering_id: int) -> int | None:
    row = session.scalar(
        select(m.Term.institution_id)
        .join(m.Offering, m.Offering.term_id == m.Term.id)
        .where(m.Offering.id == offering_id)
    )
    return int(row) if row is not None else None


def _reject_foreign_groups(session: DbSession, offering_id: int, group_ids: Sequence[int]) -> None:
    """Refuse attendee groups belonging to another institution.

    Reachable only when the chain is complete: a group knows its institution through
    ``program -> department -> institution``, and both links are optional. Where it
    breaks the check cannot be made and is not guessed at — a partial guard that is
    honest about its edges beats one that invents an answer.
    """
    if not group_ids:
        return
    expected = _institution_of_offering(session, offering_id)
    if expected is None:
        return

    foreign = session.scalars(
        select(m.StudentGroup.id)
        .join(m.Program, m.Program.id == m.StudentGroup.program_id)
        .join(m.Department, m.Department.id == m.Program.department_id)
        .where(
            m.StudentGroup.id.in_(list(group_ids)),
            m.Department.institution_id != expected,
        )
    ).all()
    if foreign:
        raise ConflictError(
            f"groups {sorted(int(g) for g in foreign)} belong to another institution",
            blockers={"foreign_groups": len(foreign)},
        )


def _resolve(
    session: DbSession,
    *,
    attendee_ids: Sequence[int],
    instructor_ids: Sequence[int],
    feature_ids: Sequence[int],
) -> tuple[list[m.StudentGroup], list[m.Instructor], list[m.Feature]]:
    """Load the rows an association should point at, failing on the offending field."""
    _check_exist(session, m.StudentGroup, {int(i) for i in attendee_ids}, "attendee_ids")
    _check_exist(session, m.Instructor, {int(i) for i in instructor_ids}, "instructor_ids")
    _check_exist(session, m.Feature, {int(i) for i in feature_ids}, "required_feature_ids")

    groups = list(
        session.scalars(select(m.StudentGroup).where(m.StudentGroup.id.in_(list(attendee_ids))))
    )
    instructors = list(
        session.scalars(select(m.Instructor).where(m.Instructor.id.in_(list(instructor_ids))))
    )
    features = list(session.scalars(select(m.Feature).where(m.Feature.id.in_(list(feature_ids)))))
    return groups, instructors, features


# --------------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------------


def list_templates(session: DbSession, *, offering_id: int) -> list[d.SessionTemplate]:
    _get_or_404(session, m.Offering, offering_id)
    rows = session.scalars(
        select(m.SessionTemplate)
        .where(m.SessionTemplate.offering_id == offering_id)
        .order_by(m.SessionTemplate.id)
    )
    return [mappers.template_to_domain(row) for row in rows]


def get_template(session: DbSession, template_id: int) -> d.SessionTemplate:
    return mappers.template_to_domain(_get_or_404(session, m.SessionTemplate, template_id))


def create_template(
    session: DbSession,
    *,
    offering_id: int,
    kind: d.SessionKind = d.SessionKind.LECTURE,
    duration_slots: int,
    per_week: int,
    split_per_attendee: bool = False,
    attendee_ids: Sequence[int],
    instructor_ids: Sequence[int] = (),
    required_feature_ids: Sequence[int] = (),
) -> d.SessionTemplate:
    """Add a component to an offering's weekly pattern.

    The duration is checked against the term's grid rather than only against itself: a
    three-hour lab in a week of two-hour mornings is a template that can never be
    placed, and finding that out at solve time — after everything else is authored —
    is the kind of late failure Decision #29 exists to prevent.
    """
    offering = _get_or_404(session, m.Offering, offering_id)
    _reject_foreign_groups(session, offering_id, attendee_ids)
    _reject_unplaceable_duration(session, offering.term_id, duration_slots)

    groups, instructors, features = _resolve(
        session,
        attendee_ids=attendee_ids,
        instructor_ids=instructor_ids,
        feature_ids=required_feature_ids,
    )
    _validated(
        d.SessionTemplate,
        offering_id=offering_id,
        kind=kind,
        duration_slots=duration_slots,
        per_week=per_week,
        split_per_attendee=split_per_attendee,
        attendee_ids=frozenset(attendee_ids),
        instructor_ids=frozenset(instructor_ids),
        required_features=frozenset(required_feature_ids),
    )

    row = m.SessionTemplate(
        offering_id=offering_id,
        kind=kind.value,
        duration_slots=duration_slots,
        per_week=per_week,
        split_per_attendee=split_per_attendee,
    )
    row.attendees = groups
    row.instructors = instructors
    row.required_features = features
    session.add(row)
    session.flush()
    return mappers.template_to_domain(row)


def _reject_unplaceable_duration(session: DbSession, term_id: int, duration_slots: int) -> None:
    """Refuse a component longer than the teaching day it would sit in.

    Read from the term's grid through the domain rather than compared against
    ``slots_per_day`` here, so "how long a block can be" has one definition.
    """
    grid_row = session.scalar(
        select(m.TimeGrid)
        .join(m.Term, m.Term.time_grid_id == m.TimeGrid.id)
        .where(m.Term.id == term_id)
    )
    if grid_row is None:  # pragma: no cover - a term always has a grid
        return
    grid = mappers.time_grid_to_domain(grid_row)
    if not grid.start_slots_for(duration_slots):
        raise ConflictError(
            f"nothing {duration_slots} slots long fits in this term's teaching week",
            blockers={"slots_per_day": grid.slots_per_day},
        )


def update_template(
    session: DbSession, template_id: int, *, changes: Mapping[str, Any]
) -> d.SessionTemplate:
    """Change how many sessions a component produces, and who attends them.

    **Multiplicity only** — `per_week`, `split_per_attendee`, `attendee_ids`. Shape
    (`kind`, `duration_slots`, instructors, features) is fixed at creation and is not in
    `SessionTemplateUpdate` either.

    The reason is that shape is *copied* into each session, so a session can diverge:
    one lab running long is a real thing to want, and `PATCH /sessions/{id}` exists for
    it. There is no honest way to propagate a shape change afterwards. Overwriting would
    silently revert those deliberate edits; not overwriting would leave a component and
    its sessions disagreeing with nothing to say which is right. Nothing records whether
    a session diverged, so the two cases cannot be told apart.

    Changing shape therefore means deleting the component and adding it again, which
    Decision #54 makes a clean operation with a visible guard.

    This does **not** touch sessions. Expansion reconciles them, and separating the two
    is what lets the caller see what an edit would cost before paying it.
    """
    row = _get_or_404(session, m.SessionTemplate, template_id)

    attendees = changes.get("attendee_ids")
    if attendees is not None:
        _reject_foreign_groups(session, row.offering_id, attendees)
        _check_exist(session, m.StudentGroup, {int(i) for i in attendees}, "attendee_ids")

    _validated(
        d.SessionTemplate,
        offering_id=row.offering_id,
        kind=d.SessionKind(row.kind),
        duration_slots=row.duration_slots,
        per_week=int(changes.get("per_week", row.per_week)),
        split_per_attendee=bool(changes.get("split_per_attendee", row.split_per_attendee)),
        attendee_ids=frozenset(
            attendees if attendees is not None else [g.id for g in row.attendees]
        ),
        instructor_ids=frozenset(int(i.id) for i in row.instructors),
        required_features=frozenset(int(f.id) for f in row.required_features),
    )

    for field in ("per_week", "split_per_attendee"):
        if field in changes:
            setattr(row, field, changes[field])
    if attendees is not None:
        row.attendees = list(
            session.scalars(select(m.StudentGroup).where(m.StudentGroup.id.in_(list(attendees))))
        )

    session.flush()
    return mappers.template_to_domain(row)


def delete_template(session: DbSession, template_id: int) -> None:
    """Remove a component, and the sessions it generated with it.

    Deleting a template *is* the explicit act of removing that component from the
    weekly pattern, so taking its generated sessions is what the caller means — they are
    derived data with no independent existence. What is refused is doing so while any of
    them are **scheduled**, which is somebody's placed timetable rather than derived
    data. Symmetric with expansion's rule in part 4.

    The alternative — refusing whenever sessions exist at all — deadlocks: sessions are
    only removed by expansion, expansion reconciles against the templates that exist,
    and so a template that had ever been expanded could never be deleted.
    """
    row = _get_or_404(session, m.SessionTemplate, template_id)
    generated = [
        int(i)
        for i in session.scalars(
            select(m.Session.id).where(m.Session.template_id == template_id)
        ).all()
    ]

    scheduled = _scheduled_count(session, generated)
    if scheduled:
        raise ConflictError(
            f"{scheduled} of this component's sessions are scheduled and cannot be removed",
            blockers={"scheduled_sessions": scheduled},
        )

    for victim in session.scalars(
        select(m.Session).where(m.Session.template_id == template_id)
    ).all():
        session.delete(victim)
    session.delete(row)
    session.flush()


def template_session_count(session: DbSession, template_id: int) -> int:
    """Sessions this template has actually generated, which is not the same as the
    number it *would* generate — that is `SessionTemplate.session_count`, and the two
    differing is precisely what expansion reconciles."""
    return int(
        session.scalar(
            select(func.count()).select_from(m.Session).where(m.Session.template_id == template_id)
        )
        or 0
    )


# --------------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------------


def list_sessions(
    session: DbSession,
    *,
    term_id: int,
    offering_id: int | None = None,
    group_id: int | None = None,
    instructor_id: int | None = None,
) -> list[d.Session]:
    """Every session in a term, narrowed.

    The filters exist so the client can draw one person's or one group's week without
    fetching the whole term and narrowing locally — which for a department is thousands
    of rows to render a dozen.
    """
    _get_or_404(session, m.Term, term_id)
    query = select(m.Session).where(m.Session.term_id == term_id)

    if offering_id is not None:
        query = query.where(m.Session.offering_id == offering_id)
    if group_id is not None:
        query = query.where(
            m.Session.id.in_(
                select(m.session_attendee.c.session_id).where(
                    m.session_attendee.c.group_id == group_id
                )
            )
        )
    if instructor_id is not None:
        query = query.where(
            m.Session.id.in_(
                select(m.session_instructor.c.session_id).where(
                    m.session_instructor.c.instructor_id == instructor_id
                )
            )
        )

    query = query.order_by(m.Session.offering_id, m.Session.template_id, m.Session.occurrence)
    return [mappers.session_to_domain(row) for row in session.scalars(query)]


def get_session(session: DbSession, session_id: int) -> d.Session:
    return mappers.session_to_domain(_get_or_404(session, m.Session, session_id))


def update_session(session: DbSession, session_id: int, *, changes: Mapping[str, Any]) -> d.Session:
    """Let one session diverge from its template.

    Lengthening a single lab, or requiring a projector for one of three lectures, is a
    real thing to want, and the domain expects it: duration, kind and requirements are
    *copied* into a session precisely so editing the template afterwards cannot alter
    timetables already built from it.

    **Refused while the session is scheduled.** Every editable field here changes
    whether an existing placement is still legal — a longer session may run through a
    break or off the end of the day, a new required feature may not exist in the
    assigned room, a new instructor may already be teaching then. Allowing the edit
    would leave a published timetable quietly invalid, which is the failure this whole
    phase keeps guarding against. The draft is discarded or the session unpinned first.
    """
    row = _get_or_404(session, m.Session, session_id)

    scheduled = _scheduled_count(session, [session_id])
    if scheduled:
        raise ConflictError(
            "this session is scheduled; unschedule it before editing",
            blockers={"assignments": scheduled},
        )

    duration = int(changes.get("duration_slots", row.duration_slots))
    if "duration_slots" in changes:
        _reject_unplaceable_duration(session, row.term_id, duration)

    instructors = changes.get("instructor_ids")
    features = changes.get("required_feature_ids")
    _validated(
        d.Session,
        offering_id=row.offering_id,
        template_id=row.template_id,
        kind=d.SessionKind(row.kind),
        duration_slots=duration,
        occurrence=row.occurrence,
        attendee_ids=frozenset(g.id for g in row.attendees),
        instructor_ids=frozenset(
            instructors if instructors is not None else [i.id for i in row.instructors]
        ),
        required_features=frozenset(
            features if features is not None else [f.id for f in row.required_features]
        ),
    )

    if "duration_slots" in changes:
        row.duration_slots = duration
    if instructors is not None:
        _check_exist(session, m.Instructor, {int(i) for i in instructors}, "instructor_ids")
        row.instructors = list(
            session.scalars(select(m.Instructor).where(m.Instructor.id.in_(list(instructors))))
        )
    if features is not None:
        _check_exist(session, m.Feature, {int(i) for i in features}, "required_feature_ids")
        row.required_features = list(
            session.scalars(select(m.Feature).where(m.Feature.id.in_(list(features))))
        )

    session.flush()
    return mappers.session_to_domain(row)


def headcount_of(session: DbSession, attendee_ids: Sequence[int]) -> int:
    """How many students a session must seat.

    Resolved to **leaves and then unioned** rather than summed per group, because two
    attendee groups may overlap — an elective and the intake it draws from — and summing
    would book a room twice the size it needs. The resolution itself is the domain's.
    """
    if not attendee_ids:
        return 0
    known = groups_repo.group_set(session)
    leaves: set[StudentGroupId] = set()
    for group_id in attendee_ids:
        gid = StudentGroupId(group_id)
        if gid in known:
            leaves |= set(known.leaves_of(gid))
    return sum(known.get(leaf).size for leaf in leaves)
