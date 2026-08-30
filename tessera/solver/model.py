"""A term, expressed as a CP-SAT model.

**Not the obvious model.** Decision #35 is 🔒 and forbids `x[session, period, room]`: at
department scale that is 1.6 M booleans at 30-minute slots and **2.8 s merely to construct**,
before any search. It works in CB-CTT because those instances are roughly 300 times smaller, so
Phase 0.1's success with it is not evidence it would work here.

What #35 prescribes, and what this builds:

* **an integer `start` per session**, not a boolean per period — the period dimension is the
  one that made the cube explode;
* **a presence literal only for (session, room) pairs that are actually possible** — capacity
  and features rule most rooms out before search, and `Room.can_host` already knows;
* **optional intervals** rather than pairwise clash booleans, so `add_no_overlap` does the work.

**Nothing is scored here.** 4.2 finds *a* valid timetable; 4.3 adds the objective and 4.4 the
search that makes it good. A variable introduced here with an unclamped domain is where 0.1's
unsound lower bound would live again, so the shapes are kept tight even though nothing yet
reads them.

**Built from the validator's `Snapshot`** (D1). Sharing the *state* is what stops the solver
and the validator disagreeing about what is in the term; it is not sharing the *reading of the
rules*, which stays independent for the reason 0.1 recorded — two separate readings agreeing
is evidence, and one reading agreeing with itself is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from tessera.domain.entities import Session, WeekPattern
from tessera.domain.ids import RoomId, SessionId
from tessera.domain.time_grid import Slot
from tessera.domain.validation import Snapshot
from tessera.domain.validation.snapshot import Placement

if TYPE_CHECKING:
    from collections.abc import Sequence


class UnsatisfiableError(Exception):
    """A session that cannot go anywhere at all, found while building rather than searching.

    Raised only when the *model* cannot be written — a session with no room able to hold it,
    or no legal hour in the week. CP-SAT would report this as `INFEASIBLE` after searching,
    which is a slower way to learn something arithmetic already knew, and a worse one: the
    message here names the session.
    """


@dataclass(frozen=True, slots=True)
class Candidate:
    """One session in one room it could actually occupy."""

    session: SessionId
    room: RoomId
    present: cp_model.IntVar
    """True when this session is placed in this room. Exactly one per session is true."""

    interval: cp_model.IntervalVar
    """The room's time, which includes its turnaround — a lab that needs twenty minutes to
    clear is *in use* for those twenty minutes. Optional on `present`, so a room's
    `add_no_overlap` only sees the sessions actually in it."""


@dataclass
class Model:
    """The CP-SAT model, and the handles needed to read a solution back out."""

    cp: cp_model.CpModel
    starts: dict[SessionId, cp_model.IntVar] = field(default_factory=dict)
    candidates: dict[SessionId, list[Candidate]] = field(default_factory=dict)
    teaching: dict[SessionId, cp_model.IntervalVar] = field(default_factory=dict)
    """When the people are busy — duration only. A room's turnaround is the room's time; the
    students have left and the instructor has stopped teaching (#190)."""

    legal: dict[SessionId, tuple[Slot, ...]] = field(default_factory=dict)
    """Every hour each session could begin at — the start's domain, kept in a form Python can
    read. 4.3 needs it to know which days and hours a session can reach, and deriving that
    back out of a CP-SAT variable's flattened domain would be a second answer to a question
    this already knew."""

    def room_of(self, solver: cp_model.CpSolver, session: SessionId) -> RoomId:
        for candidate in self.candidates[session]:
            if solver.boolean_value(candidate.present):
                return candidate.room
        raise AssertionError(f"session {session} was placed in no room")  # pragma: no cover


def build(snapshot: Snapshot) -> Model:
    """Turn a term into a model that has a solution exactly when the term has a timetable."""
    model = Model(cp=cp_model.CpModel())

    for session_id, session in sorted(snapshot.sessions.items()):
        _session(model, snapshot, session_id, session)

    _rooms_hold_one_thing(model, snapshot)
    _people_are_in_one_place(model, snapshot)
    _pins(model, snapshot)
    return model


def _session(model: Model, snapshot: Snapshot, session_id: SessionId, session: Session) -> None:
    """The variables for one session: when it starts, and which room it is in.

    The start's domain is the set of hours it could legally begin — not a range with
    constraints bolted on afterwards (D2). `TimeGrid.can_hold` already refuses the three
    impossible placements (past the end of the week, across midnight, through a break) and
    says which, so re-deriving them as arithmetic would be a second answer to a settled
    question.
    """
    legal = _legal_starts(snapshot, session_id, session)
    if not legal:
        raise UnsatisfiableError(
            f"session {session_id} has no hour it could start in: every slot is a break, "
            "runs past the end of a day, or falls when its instructor is unavailable"
        )

    start = model.cp.new_int_var_from_domain(
        cp_model.Domain.from_values(sorted(legal)), f"start[{session_id}]"
    )
    model.starts[session_id] = start
    model.legal[session_id] = tuple(sorted(legal))
    model.teaching[session_id] = model.cp.new_fixed_size_interval_var(
        start, session.duration_slots, f"teaching[{session_id}]"
    )

    candidates = _candidates(model, snapshot, session_id, session, start, legal)
    if not candidates:
        raise UnsatisfiableError(
            f"session {session_id} has no room that can hold it — check capacity, the "
            "features it requires, and when those rooms are closed"
        )
    model.candidates[session_id] = candidates

    # Exactly one, which is what makes a solution *complete* as well as feasible. 4.1's D6
    # keeps completeness a separate question precisely so a solver cannot pass by leaving
    # sessions out, and this is the constraint that stops it.
    model.cp.add_exactly_one(c.present for c in candidates)


def _legal_starts(snapshot: Snapshot, session_id: SessionId, session: Session) -> set[Slot]:
    """Every hour this session could begin, before rooms are considered.

    Instructor unavailability is applied here rather than as a constraint: it does not depend
    on which room is chosen, so it belongs in the domain where the solver never has to
    explore it.
    """
    grid = snapshot.grid
    away = {
        slot
        for instructor in session.instructor_ids
        for slot in range(grid.slot_count)
        if (instructor, slot) in snapshot.instructor_away
    }
    return {
        start
        for start in range(grid.slot_count)
        if grid.can_hold(start, session.duration_slots)
        and not away & set(range(start, start + session.duration_slots))
    }


def _candidates(
    model: Model,
    snapshot: Snapshot,
    session_id: SessionId,
    session: Session,
    start: cp_model.IntVar,
    legal: set[Slot],
) -> list[Candidate]:
    """The rooms this session could be in, and an optional interval for each.

    This is #35's pruning, and it is where most of the model's size is decided: a lecture for
    two hundred with a projector fits perhaps three rooms out of forty, so forty booleans
    become three. `Room.can_host` answers it — the same function the `room_fits_group` and
    `room_has_required_features` invariants use, so the solver cannot consider a room the
    validator would reject.
    """
    headcount = snapshot.headcount(session)
    found: list[Candidate] = []

    for room_id, room in sorted(snapshot.rooms.items()):
        if not room.can_host(headcount, session.required_features, session.required_counts):
            continue
        # A room closed during the hours this session would occupy is not a candidate for
        # those hours. Computed rather than constrained, for the same reason as the starts.
        usable = {
            begin
            for begin in legal
            if not any(
                (room_id, slot) in snapshot.room_closed
                for slot in range(begin, begin + session.duration_slots + room.turnaround_slots)
            )
        }
        if not usable:
            continue

        present = model.cp.new_bool_var(f"in[{session_id},{room_id}]")
        if usable != legal:
            # Only where it bites. An unconditional table constraint per candidate would be
            # thousands of them saying nothing.
            model.cp.add_allowed_assignments(
                [start], [(v,) for v in sorted(usable)]
            ).only_enforce_if(present)
        found.append(
            Candidate(
                session=session_id,
                room=room_id,
                present=present,
                interval=model.cp.new_optional_fixed_size_interval_var(
                    start,
                    session.duration_slots + room.turnaround_slots,
                    present,
                    f"holds[{session_id},{room_id}]",
                ),
            )
        )
    return found


def _rooms_hold_one_thing(model: Model, snapshot: Snapshot) -> None:
    """`room_not_double_booked`, as a constraint rather than a check."""
    by_room: dict[RoomId, list[Candidate]] = {}
    for candidates in model.candidates.values():
        for candidate in candidates:
            by_room.setdefault(candidate.room, []).append(candidate)

    for room_id, sharing in sorted(by_room.items()):
        _no_overlap(
            model,
            snapshot,
            [(c.session, c.interval) for c in sharing],
            name=f"room {room_id}",
        )


def _people_are_in_one_place(model: Model, snapshot: Snapshot) -> None:
    """`instructor_not_double_booked` and `group_not_double_booked`.

    Groups are taken by **leaf**, exactly as the validator does: a lecture to an intake and a
    lab to one of its batches collide, and nothing names the same group twice. Indexing the
    named group instead would let that pair through, which is the failure a solver produces
    and a person discovers at the door.
    """
    for _instructor, sessions in sorted(snapshot.sessions_of_instructor.items()):
        _no_overlap(
            model, snapshot, [(s, model.teaching[s]) for s in sessions], name="an instructor"
        )
    for _group, sessions in sorted(snapshot.sessions_of_group.items()):
        _no_overlap(model, snapshot, [(s, model.teaching[s]) for s in sessions], name="a group")


def _no_overlap(
    model: Model,
    snapshot: Snapshot,
    sharing: Sequence[tuple[SessionId, cp_model.IntervalVar]],
    *,
    name: str,
) -> None:
    """Nothing here may overlap anything else here — except across weeks that never meet.

    Two labs at one hour in one room, one in odd weeks and one in even, do not collide. A
    single `add_no_overlap` cannot say "except these pairs", so the sessions are split by week
    pattern instead: every-week sessions belong to both halves, odd and even to one each.
    Two calls, exact, and no pairwise booleans.

    `name` is unused by the solver and kept for the model dump, which is the only way to read
    one of these back when it says INFEASIBLE.
    """
    if len(sharing) < 2:
        return
    for pattern in (WeekPattern.ODD_WEEKS, WeekPattern.EVEN_WEEKS):
        together = [
            interval
            for session_id, interval in sharing
            if snapshot.sessions[session_id].week_pattern.coincides_with(pattern)
        ]
        if len(together) > 1:
            model.cp.add_no_overlap(together)


def _pins(model: Model, snapshot: Snapshot) -> None:
    """A pinned assignment is a fixed variable (D3).

    Decision #10 put `is_pinned` in the schema from day one *"because retrofitting reworks the
    solver interface"*. This is the phase where that either pays off or is quietly ignored;
    it costs a few lines, which is what R2 promised.
    """
    pinned = {
        session_id: placement
        for session_id, placement in sorted(snapshot.placements.items())
        if placement.is_pinned
    }

    for session_id, placement in pinned.items():
        model.cp.add(model.starts[session_id] == placement.start_slot)
        if not any(c.room == placement.room_id for c in model.candidates[session_id]):
            raise UnsatisfiableError(
                f"session {session_id} is pinned to room {placement.room_id}, which cannot "
                "hold it — check capacity, the features it requires, and when that room is "
                "closed"
            )
        for candidate in model.candidates[session_id]:
            model.cp.add(candidate.present == (1 if candidate.room == placement.room_id else 0))

    for first, second in combinations(sorted(pinned), 2):
        if _pins_collide(snapshot, pinned, first, second):
            raise UnsatisfiableError(
                f"sessions {first} and {second} are both pinned into room "
                f"{pinned[first].room_id} at the same time"
            )


def _pins_collide(
    snapshot: Snapshot,
    pinned: dict[SessionId, Placement],
    first: SessionId,
    second: SessionId,
) -> bool:
    """Two pins fighting over one room, in weeks that meet.

    The search would find this on its own and report INFEASIBLE. Saying it here names the two
    sessions and the room, which is the difference between a message somebody can act on and
    one that sends them looking.
    """
    one, two = pinned[first], pinned[second]
    if one.room_id != two.room_id:
        return False
    if not snapshot.sessions[first].week_pattern.coincides_with(
        snapshot.sessions[second].week_pattern
    ):
        return False
    return bool(set(snapshot.occupied(one)) & set(snapshot.occupied(two)))


def size(model: Model) -> tuple[int, int]:
    """Sessions and (session, room) candidates. For the measurement #35 is a warning about."""
    return len(model.starts), sum(len(c) for c in model.candidates.values())
