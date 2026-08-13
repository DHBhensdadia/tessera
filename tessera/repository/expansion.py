"""Turning weekly patterns into the sessions the solver places.

Expansion looks like generation and is **reconciliation**. The difference is the whole
of this module.

The obvious implementation deletes every session for an offering and recreates them from
the templates. That is correct exactly once. `session` cascades from `offering` and
`assignment` cascades from `session`, so the second run would silently discard a
scheduled timetable — **including pinned placements**, which are the hand-made decisions
Decision #10 exists to protect. Editing "3 lectures" to "4" must add a fourth, not
unschedule the first three.

So each session is matched to the pattern that should have produced it, by a key:

    (template, attendee set, occurrence)

Sessions matching a wanted key are **left completely alone** — not updated, not touched.
Wanted keys with no session get one. Sessions whose key is no longer wanted are removed,
unless any of them are scheduled, in which case the whole expansion is refused.

``occurrence`` counts the repeat *within* an attendee rather than flat across a split
(Decision #59): two labs a week across three sub-batches is (A1,0) (A1,1) (A2,0) … which
reads as "lab 1 of 2 for batch A1", and stays stable when anything else changes. A flat
0-5 would renumber on every edit and break the key it is part of.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from tessera.domain import entities as d
from tessera.repository import mappers
from tessera.repository import models as m
from tessera.repository.errors import ConflictError
from tessera.repository.sessions import _scheduled_count, _validated
from tessera.repository.structure import _get_or_404

# (template id, attendee ids, which repeat) — see the module docstring.
Key = tuple[int, frozenset[int], int]


def _wanted(template: m.SessionTemplate) -> list[tuple[Key, list[int]]]:
    """Every session this component should produce, keyed.

    The *number* produced is `SessionTemplate.session_count` in the domain, and this
    must agree with it — which `test_expansion.py` asserts rather than trusting. Two
    definitions of what a weekly pattern means is exactly the drift Decision #5 exists
    to prevent.
    """
    attendees = sorted(int(g.id) for g in template.attendees)
    if not attendees:  # pragma: no cover - the domain rejects this at creation
        return []

    groups: list[list[int]] = (
        [[a] for a in attendees] if template.split_per_attendee else [attendees]
    )
    wanted: list[tuple[Key, list[int]]] = []
    for group in groups:
        for occurrence in range(template.per_week):
            wanted.append(((int(template.id), frozenset(group), occurrence), group))
    return wanted


def _key_of(row: m.Session) -> Key:
    return (
        int(row.template_id or 0),
        frozenset(int(g.id) for g in row.attendees),
        int(row.occurrence),
    )


def _existing(session: DbSession, offering_id: int) -> dict[Key, list[m.Session]]:
    """Sessions this offering already has, grouped by key.

    **Sessions with no template are skipped entirely** — never matched, never removed.
    Nothing in the API can create one (there is no ``POST /sessions``), but a file
    someone has edited by hand can contain one, and quietly deleting a row this module
    did not create would be the worst possible answer.

    A list per key rather than a single row because duplicates should be impossible and
    "should be impossible" is not a reason to lose data if they occur: the first is kept
    and the rest fall out as surplus.
    """
    rows = session.scalars(
        select(m.Session).where(
            m.Session.offering_id == offering_id, m.Session.template_id.is_not(None)
        )
    ).all()

    grouped: dict[Key, list[m.Session]] = {}
    for row in rows:
        grouped.setdefault(_key_of(row), []).append(row)
    return grouped


def _create(
    session: DbSession, template: m.SessionTemplate, attendees: Sequence[int], occurrence: int
) -> None:
    """One session, with the template's shape copied rather than referenced.

    Copied because a session is the scheduled reality: editing a component afterwards
    must not silently alter timetables already built from it. The copy is why
    reconciliation adds and removes but never updates.
    """
    _validated(
        d.Session,
        offering_id=template.offering_id,
        template_id=template.id,
        kind=d.SessionKind(template.kind),
        duration_slots=template.duration_slots,
        occurrence=occurrence,
        attendee_ids=frozenset(attendees),
        instructor_ids=frozenset(int(i.id) for i in template.instructors),
        required_features=frozenset(int(f.id) for f in template.required_features),
    )
    offering = session.get(m.Offering, template.offering_id)
    assert offering is not None

    row = m.Session(
        offering_id=template.offering_id,
        term_id=offering.term_id,
        template_id=template.id,
        kind=template.kind,
        duration_slots=template.duration_slots,
        occurrence=occurrence,
    )
    row.attendees = [g for g in template.attendees if int(g.id) in set(attendees)]
    row.instructors = list(template.instructors)
    row.required_features = list(template.required_features)
    session.add(row)


def _refuse_if_scheduled(session: DbSession, surplus: Iterable[m.Session]) -> None:
    """Stop before removing anything somebody has placed.

    Deliberately **no `force` flag**. A destructive default with an escape hatch is how
    the escape hatch becomes the habit; the caller unschedules or discards the draft,
    which is a decision they can see the consequences of. If this proves too strict in
    real use it can be revisited with evidence.
    """
    victims = [int(s.id) for s in surplus]
    scheduled = _scheduled_count(session, victims)
    if scheduled:
        raise ConflictError(
            f"{scheduled} session(s) that would be removed are scheduled; "
            "unschedule them or discard the timetable first",
            blockers={"scheduled_sessions": scheduled},
        )


def expand(session: DbSession, offering_id: int) -> list[d.Session]:
    """Reconcile an offering's sessions against its weekly patterns.

    Idempotent: running it twice changes nothing the second time, which is the property
    that makes it safe to offer as a button.
    """
    _get_or_404(session, m.Offering, offering_id)
    templates = session.scalars(
        select(m.SessionTemplate).where(m.SessionTemplate.offering_id == offering_id)
    ).all()

    wanted: dict[Key, tuple[m.SessionTemplate, list[int]]] = {}
    for template in templates:
        for key, attendees in _wanted(template):
            wanted[key] = (template, attendees)

    have = _existing(session, offering_id)

    surplus: list[m.Session] = []
    for key, rows in have.items():
        surplus.extend(rows if key not in wanted else rows[1:])

    _refuse_if_scheduled(session, surplus)

    for row in surplus:
        session.delete(row)
    for key, (template, attendees) in wanted.items():
        if key not in have:
            _create(session, template, attendees, key[2])

    session.flush()
    return [
        mappers.session_to_domain(row)
        for row in session.scalars(
            select(m.Session)
            .where(m.Session.offering_id == offering_id)
            .order_by(m.Session.template_id, m.Session.occurrence, m.Session.id)
        )
    ]
