"""Turning a constraint's targets into names, in one place.

A constraint stores what it applies to as a kind and an id, because no single foreign key
can point at five tables. That is right for storage and useless to read: *"Minimise idle
gaps in the day for instructor 1"* is a sentence nobody can act on.

Resolving them needs the database, which is why `Constraint.describe` takes the names as an
argument and falls back to `kind id` when nobody supplies them — its docstring says so, and
until now nobody did. The console grew its own copy and the API kept the fallback, so every
`ConstraintRead.summary` ever sent named ids. It went unnoticed for the usual reason: the
console renders its own sentence and never reads the one on the wire, and no other client
existed until 3.4b's rules screen.

So both read from here, and there is one wording.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from tessera.domain.constraints import Constraint, TargetKind
from tessera.repository import calendar as calendar_repo
from tessera.repository import groups as groups_repo
from tessera.repository import people as people_repo
from tessera.repository import sessions as sessions_repo
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as teaching_repo

Names = dict[TargetKind, dict[int, str]]


def target_names(db: DbSession, *, term_id: int | None = None) -> Names:
    """Every targetable thing, by kind, so an id can be shown as a name.

    Loaded once per request rather than per constraint: a term with fifty rules would
    otherwise issue fifty sets of queries to answer one call.

    Sessions need a term and are skipped without one. They are the targets that most need
    naming — nobody chose "session 4" and nobody can recognise it — so a caller that has a
    term should pass it.
    """
    names: Names = {
        TargetKind.INSTRUCTOR: {int(x.id or 0): x.name for x in people_repo.list_instructors(db)},
        TargetKind.GROUP: {int(x.id or 0): x.name for x in groups_repo.list_groups(db)},
        TargetKind.ROOM: {int(x.id or 0): x.name for x in structure_repo.list_rooms(db)},
        TargetKind.COURSE: {
            int(x.id or 0): f"{x.code} {x.name}" for x in teaching_repo.list_courses(db)
        },
        TargetKind.SESSION: {},
    }
    if term_id is not None:
        courses = {int(c.id or 0): c.code for c in teaching_repo.list_courses(db)}
        offerings = {
            int(o.id or 0): courses.get(int(o.course_id or 0), "?")
            for o in calendar_repo.list_offerings(db, term_id=term_id)
        }
        names[TargetKind.SESSION] = {
            int(s.id or 0): (
                f"{offerings.get(int(s.offering_id or 0), '?')} {s.kind.value} {s.occurrence}"
            )
            for s in sessions_repo.list_sessions(db, term_id=term_id)
        }
    return names


def sentence(item: Constraint, names: Names) -> str:
    """The rule as a sentence, with its targets named.

    An id with no name behind it still reads as `kind id` rather than being dropped: a
    target pointing at something deleted is worth seeing, and a sentence that silently
    omits it would describe a rule that is not the stored one.
    """
    named = [
        names.get(target.kind, {}).get(target.id, f"{target.kind.value} {target.id}")
        for target in sorted(item.targets, key=lambda t: (t.kind.value, t.id))
    ]
    return item.describe(", ".join(named))
