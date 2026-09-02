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
    from collections.abc import Mapping, Sequence


class UnsatisfiableError(Exception):
    """A session that cannot go anywhere at all, found while building rather than searching.

    Raised only when the *model* cannot be written — a session with no room able to hold it,
    or no legal hour in the week. CP-SAT would report this as `INFEASIBLE` after searching,
    which is a slower way to learn something arithmetic already knew, and a worse one: the
    message here names the session.
    """


@dataclass(frozen=True, slots=True)
class Formulation:
    """The three model-level levers P5 names as untested headroom — and what measuring them said.

    P5 asks for these to be tried *before* assuming the outer search must do all the work.
    They were, on the same instances at the same deterministic budget, and **two of the three
    do not pay**. The defaults below are that measurement rather than a preference.

    The reason they are flags at all is #207: grouping interchangeable rooms under
    `add_cumulative` was obviously better on paper, cut the ceiling model by a factor of five
    hundred, and then timed out at 30 s on an instance the per-room model solved in 5.45. A
    lever nobody has weighed is a guess with a name on it.
    """

    symmetry: bool = False
    """Fill interchangeable rooms in order, so forty identical rooms stop giving every
    timetable 40! relabellings for the search to walk through.

    **Off: the effect is smaller than the seed's.** On one seed it looked like a 13 % gain;
    over three it was 520 against 558 on a generated department and *worse* on the real
    instances, inside a run-to-run spread of 27 %. And on `comp11` it is not a small effect
    but no effect at all — a real room estate is heterogeneous, so no two rooms are
    interchangeable and the two formulations produce identical timetables on every seed.

    Kept rather than deleted because part 2 re-measures it where the argument is different:
    inside a Fix-and-Optimize sub-problem a handful of free sessions compete for the same
    identical rooms, so the symmetry is a far larger share of a far smaller search space."""

    redundant: bool = False
    """State the obvious consequence — no more sessions run at once than there are rooms —
    as a `cumulative` **alongside** the per-room no-overlap. #207 measured cumulative as a
    poor *substitute*; it says nothing about it as an addition.

    **Off, for the same reason and with the same caveat.** Medians of 2964 against 3018, and
    1542 against 1395, on seed spreads several times wider."""

    hint: bool = True
    """Start from the timetable already in the term, where there is one.

    **On, and this one is not about speed.** Re-solving `comp11` after handing it back its own
    timetable, which scored 1395, returned **1618** without the hint and **1395** with it: told
    to re-optimise, the solver produced something worse than what the person already had,
    because it began from nothing and the budget ran out somewhere else.

    **It is not a floor, and it was worth checking rather than assuming.** A hint is advice,
    not a constraint: on a department of 150 sessions given a budget too small to find anything
    at all, the hinted solve returned `OUT_OF_TIME` exactly as the unhinted one did, even though
    it had been handed a complete valid timetable. #225 had already noted the same thing from
    the other direction. What the hint buys is a better answer when the search gets far enough
    to have one — making that answer *better* than the incumbent is the outer loop's job."""

    capacity_is_priced: bool = False
    """Let a session into a room too small for it, and leave the overflow to the objective.

    **Off, and it must stay off for anything Tessera does.** A room that seats sixty seats
    sixty, and #213 keeps that a hard invariant knowing what it costs: `comp01` has 64 lectures
    needing a room for 31 and a week containing 60 such room-periods, so Tessera refuses a
    timetable the University of Udine actually ran.

    It exists because **CB-CTT prices capacity at one point per standing student** and 4.5's
    benchmark has to compute the published metric rather than a stricter one of our own. Under
    a stricter rule the comparison would be against a different problem, and losing it would
    prove nothing.

    Note where this sits: capacity is a *filter on candidate rooms* (`_candidates`), not a
    constraint that could be dropped, and a session with no room large enough raises
    `UnsatisfiableError` before any search. So relaxing it means **generating candidates
    differently**, which is why it is a formulation flag rather than something the objective can
    undo, and why `tessera.bench` is a leaf no part of the product may import."""


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


def build(
    snapshot: Snapshot,
    formulation: Formulation | None = None,
    fixed: Mapping[SessionId, Placement] | None = None,
) -> Model:
    """Turn a term into a model that has a solution exactly when the term has a timetable.

    `formulation` switches the levers of §2.4 on. None of them changes which timetables are
    legal — that is what the tests around each of them assert, and for the symmetry break it
    is the assertion that matters most, because an over-strong break removes valid answers and
    the symptom is a slightly worse optimum nobody would attribute to the room grouping.

    `fixed` holds the sessions a Fix-and-Optimize round is not moving, **and they are frozen
    by narrowing their domains rather than by constraining them** (D3). The distinction is the
    whole reason the loop can exist. A session pinned by a constraint still owns a boolean for
    every hour it could have started at and every room it could have been in, and the
    objective channels all of them — so #225's nine-fold model would be built in full every
    round and merely told not to use most of it. A session with one legal start and one
    candidate room contributes one boolean to `Terms.at`, one to `in_room`, and a `busy` that
    collapses to a single literal. The channelling is then built only for what the round left
    free, which is what makes a sub-problem small rather than merely constrained.

    User pins are deliberately **not** routed through this. `_pins` keeps them, because it
    also says which pin is impossible and which two collide, and a narrowed domain reports
    that as "this session has no hour it could start in" — a true sentence about the wrong
    thing. There are a handful of pins and hundreds of frozen sessions, so the mechanism that
    matters for size is not the one that matters for the message.
    """
    formulation = formulation or Formulation()
    fixed = fixed or {}
    model = Model(cp=cp_model.CpModel())

    for session_id, session in sorted(snapshot.sessions.items()):
        _session(model, snapshot, session_id, session, formulation, fixed.get(session_id))

    _rooms_hold_one_thing(model, snapshot)
    _people_are_in_one_place(model, snapshot)
    _pins(model, snapshot)

    if formulation.symmetry:
        _fill_alike_rooms_in_order(model, snapshot)
    if formulation.redundant:
        _no_more_at_once_than_there_are_rooms(model, snapshot)
    if formulation.hint:
        _start_from_what_is_already_placed(model, snapshot)
    return model


def _session(
    model: Model,
    snapshot: Snapshot,
    session_id: SessionId,
    session: Session,
    formulation: Formulation,
    frozen: Placement | None = None,
) -> None:
    """The variables for one session: when it starts, and which room it is in.

    The start's domain is the set of hours it could legally begin — not a range with
    constraints bolted on afterwards (D2). `TimeGrid.can_hold` already refuses the three
    impossible placements (past the end of the week, across midnight, through a break) and
    says which, so re-deriving them as arithmetic would be a second answer to a settled
    question.

    A `frozen` session narrows both domains to one value each. It keeps its variables rather
    than disappearing, because the objective scores the **whole** timetable and not the
    window: a round's cost is what the term costs, which is what makes accepting a round a
    comparison of like with like.
    """
    legal = _legal_starts(snapshot, session_id, session)
    if frozen is not None:
        legal &= {frozen.start_slot}
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

    candidates = _candidates(
        model, snapshot, session_id, session, start, legal, formulation, frozen
    )
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
    formulation: Formulation,
    frozen: Placement | None = None,
) -> list[Candidate]:
    """The rooms this session could be in, and an optional interval for each.

    This is #35's pruning, and it is where most of the model's size is decided: a lecture for
    two hundred with a projector fits perhaps three rooms out of forty, so forty booleans
    become three. `Room.can_host` answers it — the same function the `room_fits_group` and
    `room_has_required_features` invariants use, so the solver cannot consider a room the
    validator would reject.
    """
    # Zero when capacity is priced rather than required, which leaves `can_host` answering
    # about features alone. The features half is never relaxed: a lecture needing a projector
    # in a room without one is not a cost, it is a lecture that cannot happen.
    headcount = 0 if formulation.capacity_is_priced else snapshot.headcount(session)
    found: list[Candidate] = []

    for room_id, room in sorted(snapshot.rooms.items()):
        if frozen is not None and room_id != frozen.room_id:
            continue
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


def _alike(model: Model, snapshot: Snapshot) -> list[list[RoomId]]:
    """Rooms this model genuinely cannot tell apart, grouped.

    Interchangeability is not "same capacity". Two rooms of sixty are different rooms if one
    is closed on Tuesday morning, if one is in another building, or if one needs twenty
    minutes to clear — `room_closed` is per `(room, slot)`, `MINIMISE_BUILDING_CHANGES` reads
    `building_id`, and the turnaround is in the interval's length. Every one of those is in
    the key, and so is the set of sessions each room ended up a candidate for, which is the
    exact consequence of `can_host` and the closure filter rather than a second opinion about
    them.

    **A pinned room is nobody's twin.** A pin names one room, so the rooms of a class stop
    being substitutable the moment one of them is fixed — and the search would then be told a
    valid timetable is not one. Pinned rooms are excluded rather than reasoned about.
    """
    pinned = {p.room_id for p in snapshot.placements.values() if p.is_pinned}
    users: dict[RoomId, set[SessionId]] = {room_id: set() for room_id in snapshot.rooms}
    for session_id, candidates in model.candidates.items():
        for candidate in candidates:
            users[candidate.room].add(session_id)

    closures: dict[RoomId, set[Slot]] = {}
    for room_id, slot in snapshot.room_closed:
        closures.setdefault(room_id, set()).add(slot)

    classes: dict[tuple[object, ...], list[RoomId]] = {}
    for room_id, room in sorted(snapshot.rooms.items()):
        if room_id in pinned or not users[room_id]:
            continue
        key = (
            frozenset(users[room_id]),
            room.capacity,
            frozenset(room.features),
            tuple(sorted(room.feature_counts.items())),
            room.building_id,
            room.turnaround_slots,
            frozenset(closures.get(room_id, ())),
        )
        classes.setdefault(key, []).append(room_id)
    return [rooms for rooms in classes.values() if len(rooms) > 1]


def _fill_alike_rooms_in_order(model: Model, snapshot: Snapshot) -> None:
    """Interchangeable rooms are used in order, so their permutations stop being answers.

    Forty rooms nothing can distinguish give every timetable 40! relabellings, and the search
    walks them as though each were a different timetable. Value precedence keeps exactly one
    of each set: **a room is used for the first time only after the room before it has been.**

    Written over ranks rather than over pairs of literals. The obvious encoding says *this
    session may be in room k+1 only if some earlier session is in room k*, which is a clause
    per (room, session) pair carrying every earlier session in it — quadratic in the sessions,
    five million literals at department scale. Ranking each session within the class and
    carrying the running maximum is the same statement in a chain: one integer per session,
    independent of how many rooms the class holds.

    `rank` is 1-based so that **0 means "in none of these rooms"**, which is a real case — a
    session may be placed in a room outside the class — and a 0-based rank would confuse it
    with the first room.
    """
    for alike in _alike(model, snapshot):
        places = {room_id: index for index, room_id in enumerate(alike, start=1)}
        # A session can be a candidate for two different classes of room, so the class is in
        # the name. Duplicate names are legal and turn the model dump — the only way to read
        # one of these back when it says INFEASIBLE — into a guessing game.
        like = alike[0]
        users = sorted(
            session_id
            for session_id, candidates in model.candidates.items()
            if any(candidate.room in places for candidate in candidates)
        )

        highest: cp_model.IntVar | None = None
        for position, session_id in enumerate(users):
            here = [
                (candidate.present, places[candidate.room])
                for candidate in model.candidates[session_id]
                if candidate.room in places
            ]
            rank = model.cp.new_int_var(0, len(alike), f"rank[{session_id},{like}]")
            model.cp.add(
                rank
                == cp_model.LinearExpr.weighted_sum(
                    [present for present, _ in here], [place for _, place in here]
                )
            )
            model.cp.add(rank <= 1 if highest is None else rank <= highest + 1)

            # The last session has nobody after it to constrain, so its running maximum would
            # be a variable nothing reads.
            if position < len(users) - 1:
                reached = model.cp.new_int_var(0, len(alike), f"reached[{session_id},{like}]")
                if highest is None:
                    model.cp.add(reached == rank)
                else:
                    model.cp.add_max_equality(reached, [highest, rank])
                highest = reached


def _no_more_at_once_than_there_are_rooms(model: Model, snapshot: Snapshot) -> None:
    """The consequence the per-room no-overlap already implies, said out loud.

    Every session is in exactly one room and a room holds one thing, so at any hour the number
    of sessions being taught cannot exceed the number of rooms. CP-SAT has to derive that from
    the per-room constraints; stating it gives the propagator one global fact instead of forty
    local ones, and it is what rules out a half-built assignment that has already overfilled
    the week.

    Teaching time rather than room time, deliberately: a room's turnaround extends the room's
    interval past the class, and counting it here would claim a room is occupied when the
    argument above does not say so. Under-stating a redundant constraint is safe; over-stating
    one removes timetables.

    Added only where it can bite. With more rooms than sessions it is a constraint that is
    true before the search starts.
    """
    for pattern in (WeekPattern.ODD_WEEKS, WeekPattern.EVEN_WEEKS):
        running = [
            model.teaching[session_id]
            for session_id in sorted(model.teaching)
            if snapshot.sessions[session_id].week_pattern.coincides_with(pattern)
        ]
        if len(running) > len(snapshot.rooms):
            model.cp.add_cumulative(running, [1] * len(running), len(snapshot.rooms))


def start_from(model: Model, placements: Mapping[SessionId, Placement]) -> None:
    """Hand the search a timetable to begin at, from wherever the caller got one.

    The loop's warm start. `Formulation.hint` reads the term's own placements, which is right
    for re-optimising what a person already has and useless to a round, whose incumbent came
    from the previous round and is in no snapshot.

    A placement that no longer fits is left out rather than repaired — see below.
    """
    for session_id, placement in sorted(placements.items()):
        if session_id not in model.starts or placement.start_slot not in model.legal[session_id]:
            continue
        candidates = model.candidates[session_id]
        if not any(candidate.room == placement.room_id for candidate in candidates):
            continue
        model.cp.add_hint(model.starts[session_id], placement.start_slot)
        for candidate in candidates:
            model.cp.add_hint(candidate.present, int(candidate.room == placement.room_id))


def _start_from_what_is_already_placed(model: Model, snapshot: Snapshot) -> None:
    """Hand the search the timetable the term already has, as a starting point rather than a rule.

    A hint is not a constraint: CP-SAT is free to walk away from it, and a term with nothing
    placed simply has nothing to say. What it buys is the difference between re-optimising and
    restarting, which is the whole of *"keep what I have, make it better"* — R2 names
    `AddHint()` as the reason that feature is not a separate mode.

    A placement that no longer fits — a room since made too small, an hour since made a break —
    is left out rather than repaired. Hinting a value outside a variable's domain asks the
    solver to make sense of a contradiction, and the honest answer is that this session has no
    starting point.
    """
    start_from(model, snapshot.placements)


def size(model: Model) -> tuple[int, int]:
    """Sessions and (session, room) candidates. For the measurement #35 is a warning about."""
    return len(model.starts), sum(len(c) for c in model.candidates.values())
