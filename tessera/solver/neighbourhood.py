"""Which sessions a round is allowed to move.

A Fix-and-Optimize round freezes almost everything and re-solves a window, so the choice of
window is the search. R2 lists three shapes — a department, a day, the sessions carrying the
most penalty — and part 3 measures those against each other. This part carries the one that
has to beat all of them to be worth keeping: **a random handful**, which is the control.

Every strategy is a plain function of the term, the timetable it currently has, and a seeded
`Random`. That makes the choice testable without a solver, and it is what lets the two rules
below be properties over the whole set rather than four copies of the same assertion.

**A strategy never frees a pinned session.** Decision #10 put `is_pinned` in the schema on the
first day so that *"re-optimise around my manual edits"* would not need a solver rewrite; a
window that quietly moved a pinned session would turn that promise into a lie in the one place
nobody looks — the timetable came back better, so why read it closely.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping

from tessera.domain.entities import Unavailability
from tessera.domain.ids import AssignmentId, SessionId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Report, Snapshot, validate
from tessera.domain.validation.snapshot import Placement

type Strategy = Callable[
    [Snapshot, Mapping[SessionId, Placement], random.Random, int], frozenset[SessionId]
]


def movable(snapshot: Snapshot) -> list[SessionId]:
    """Every session a round may touch: all of them, less the ones somebody pinned."""
    return sorted(
        session_id
        for session_id in snapshot.sessions
        if not (placed := snapshot.placements.get(session_id)) or not placed.is_pinned
    )


def anywhere(
    snapshot: Snapshot,
    placed: Mapping[SessionId, Placement],
    rng: random.Random,
    window: int,
) -> frozenset[SessionId]:
    """A random handful, drawn without regard to what anything costs.

    The control, and it is here first on purpose. A strategy that reasons about the timetable
    has to be shown to beat one that does not, and the usual way that comparison goes wrong is
    that the clever strategy is never measured against anything.
    """
    choices = movable(snapshot)
    return frozenset(rng.sample(choices, min(window, len(choices))))


def one_day(
    snapshot: Snapshot,
    placed: Mapping[SessionId, Placement],
    rng: random.Random,
    window: int,
) -> frozenset[SessionId]:
    """Everything teaching on one day.

    Eight of the sixteen rules are about a day — idle hours, hours in a row, the same course
    twice, the day's share of the week's load — and none of them can be improved by moving a
    session without also being free to move what it collides with. A window scattered across
    five days holds one session of each day's problem and cannot rearrange any of them.
    """
    days: dict[int, list[SessionId]] = {}
    for session_id in movable(snapshot):
        if (where := placed.get(session_id)) is not None:
            days.setdefault(snapshot.grid.day_of(where.start_slot), []).append(session_id)
    if not days:
        return frozenset(rng.sample(movable(snapshot), 1))

    chosen = days[rng.choice(sorted(days))]
    return frozenset(rng.sample(chosen, min(window, len(chosen))))


def one_subject(
    snapshot: Snapshot,
    placed: Mapping[SessionId, Placement],
    rng: random.Random,
    window: int,
) -> frozenset[SessionId]:
    """One group's or one instructor's whole week.

    The window that can actually close a gap. An idle hour on Tuesday is bounded by the class
    before it and the class after it, and moving either is what removes it — so a strategy that
    frees one of the two and freezes the other cannot see the improvement at all.
    """
    free = set(movable(snapshot))
    subjects = [
        sessions
        for index in (snapshot.sessions_of_group, snapshot.sessions_of_instructor)
        for sessions in index.values()
        if len(set(sessions) & free) > 1
    ]
    if not subjects:
        return frozenset(rng.sample(sorted(free), 1))

    chosen = sorted(set(rng.choice(subjects)) & free)
    return frozenset(rng.sample(chosen, min(window, len(chosen))))


def worst_first(
    snapshot: Snapshot,
    placed: Mapping[SessionId, Placement],
    rng: random.Random,
    window: int,
) -> frozenset[SessionId]:
    """The sessions carrying the most cost, as the **validator** attributes it.

    Every soft violation names a session and states what it cost, so the ranking comes from the
    reading that shares none of the solver's logic (4.1's D1). Taking it from the objective
    instead would let one implementation choose the neighbourhoods that flatter it.

    Ties are broken by the seeded `Random` rather than by session id, so a term where everything
    costs the same does not free the same handful every round for ever.
    """
    blamed: dict[SessionId, int] = {}
    for violation in judge(snapshot, placed).violations:
        if not violation.is_hard:
            blamed[violation.session_id] = blamed.get(violation.session_id, 0) + violation.cost

    free = movable(snapshot)
    guilty = sorted((s for s in free if blamed.get(s)), key=lambda s: (-blamed[s], rng.random()))
    if not guilty:
        return frozenset(rng.sample(free, min(window, len(free))))
    return frozenset(guilty[:window])


def judge(snapshot: Snapshot, placed: Mapping[SessionId, Placement]) -> Report:
    """What the validator makes of a timetable the solver is holding.

    `Snapshot` indexes its placements when it is built and offers no way to attach different
    ones, so the term is rebuilt around them. The closures and preferences it was built from are
    not kept as rows, only as the three sets they were indexed into — so they are read back out
    of those, and `_the_rebuild_lost_nothing` checks that the round trip is exact rather than
    trusting it. A proper `Snapshot.replacing(...)` belongs in the domain and is in the backlog;
    reaching into `domain/` is out of scope for the 4.x phases.
    """
    rebuilt = Snapshot.of(
        grid=snapshot.grid,
        sessions=list(snapshot.sessions.values()),
        rooms=list(snapshot.rooms.values()),
        groups=snapshot.groups,
        assignments=[
            Assignment(
                id=AssignmentId(n),
                session_id=session_id,
                start_slot=placement.start_slot,
                room_id=placement.room_id,
                is_pinned=placement.is_pinned,
            )
            for n, (session_id, placement) in enumerate(sorted(placed.items()), start=1)
        ],
        unavailability=_unavailability(snapshot),
        constraints=list(snapshot.constraints),
        course_of=snapshot.course_of,
    )
    _the_rebuild_lost_nothing(snapshot, rebuilt)
    return validate(rebuilt)


def _unavailability(snapshot: Snapshot) -> list[Unavailability]:
    """The rows a snapshot was built from, recovered from what it indexed them into."""
    return [
        *(Unavailability(room_id=room, slot=slot) for room, slot in sorted(snapshot.room_closed)),
        *(
            Unavailability(instructor_id=who, slot=slot)
            for who, slot in sorted(snapshot.instructor_away)
        ),
        *(
            Unavailability(instructor_id=who, slot=slot, is_hard=False, weight=weight)
            for (who, slot), weight in sorted(snapshot.preferred_against.items())
        ),
    ]


def _the_rebuild_lost_nothing(original: Snapshot, rebuilt: Snapshot) -> None:
    """A term rebuilt for judging must be the same term.

    Cheap, and it is the guard against the failure this workaround invites: a field added to
    `Snapshot` that the rebuild does not carry would change what the validator sees without
    changing what anything says, and the strategy would rank sessions by a rulebook nobody
    wrote.
    """
    for field in ("room_closed", "instructor_away", "preferred_against", "constraints"):
        if getattr(original, field) != getattr(rebuilt, field):
            raise AssertionError(f"rebuilding the term for judging lost its {field}")


#: Every strategy there is, by name. The loop takes them from here rather than from a list, so
#: a fifth joins the tests that check the two rules by existing.
STRATEGIES: dict[str, Strategy] = {
    "anywhere": anywhere,
    "one_day": one_day,
    "one_subject": one_subject,
    "worst_first": worst_first,
}
