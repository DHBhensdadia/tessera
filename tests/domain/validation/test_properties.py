"""The real validator against an independently written one, over generated timetables.

This is 4.1's exit test. Phase 0.1 got **zero cost mismatches across 21 instances** because
the checker and the solver model were two separate readings of the same specification, and
that independence is what made its benchmark mean anything. `reference.py` reproduces the
arrangement: written from the English sentences, O(n²), nested loops, nothing shared with
`domain/validation/` but the domain objects.

**What is compared, and why not more.** Not violation objects — the two produce different
sentences, and comparing prose would test the wording. Three things:

* **feasibility** — the answer the solver acts on;
* **the penalty** — the number 4.3 will optimise, and the one 0.1 compared;
* **which rule is broken about which sessions** — as an *unordered* set of sessions, so
  neither implementation has to agree with the other about which side of a clash to report
  from. That is the observable both would naturally produce.

For a **global preference** the session set is dropped from the comparison, and that is a
statement about the rule rather than a concession. "This group's Tuesday is two hours
overloaded" is a fact about a day; the session it is hung on is where the interface puts the
marker, and the two implementations pick differently — earliest on the day, lowest id — with
neither more correct. What such a rule actually asserts is its cost, and that is compared
exactly.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tessera.domain.constraints import INVARIANTS, ConstraintKind, ConstraintScope
from tessera.domain.ids import RoomId, SessionId
from tessera.domain.timetable import Assignment
from tessera.domain.validation import Report, Snapshot, validate, validate_move
from tessera.domain.validation.rules import ON_A_MOVE
from tests.domain.validation import reference
from tests.domain.validation.generated import Instance, instances

#: Thousands, per the exit test. Slow enough to keep out of the fast loop is not a concern:
#: the instances are tiny, and this is the test the whole phase is judged by.
THOROUGH = settings(
    max_examples=2000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def snapshot_of(instance: Instance) -> Snapshot:
    return Snapshot.of(
        grid=instance.grid,
        sessions=instance.sessions,
        rooms=instance.rooms,
        groups=instance.groups,
        assignments=instance.assignments,
        unavailability=instance.unavailability,
        constraints=instance.constraints,
        course_of=instance.course_of,
    )


def read_by_reference(instance: Instance) -> reference.Reading:
    return reference.read(
        grid=instance.grid,
        sessions=instance.sessions,
        rooms=instance.rooms,
        groups=instance.groups,
        assignments=instance.assignments,
        unavailability=instance.unavailability,
        constraints=instance.constraints,
        course_of=instance.course_of,
    )


#: The seven that cannot be switched off.
INVARIANT_KEYS = frozenset(i.key for i in INVARIANTS)

#: The kinds whose violations are about a day rather than about particular sessions.
TERM_WIDE = frozenset(
    kind.value for kind in ConstraintKind if kind.spec.scope is ConstraintScope.GLOBAL
)


def comparable(
    facts: set[tuple[str, frozenset[SessionId]]],
) -> set[tuple[str, frozenset[SessionId]]]:
    """Drop the attributed session from term-wide preferences. See the module docstring."""
    return {(rule, frozenset() if rule in TERM_WIDE else sessions) for rule, sessions in facts}


def facts_of(report: Report) -> set[tuple[str, frozenset[SessionId]]]:
    """A report in the reference's terms: which rule, about which sessions, unordered."""
    return {
        (
            violation.rule,
            frozenset(
                s for s in (violation.session_id, violation.conflicting_session_id) if s is not None
            ),
        )
        for violation in report.violations
    }


@given(instances())
@THOROUGH
def test_the_two_readings_agree(instance: Instance) -> None:
    mine = validate(snapshot_of(instance))
    theirs = read_by_reference(instance)

    assert mine.is_feasible == theirs.feasible
    assert comparable(facts_of(mine)) == comparable(theirs.facts)
    assert mine.penalty == theirs.penalty


@given(instances())
@THOROUGH
def test_the_fold_equals_the_whole(instance: Instance) -> None:
    """D2's claim, over generated input rather than one hand-built case.

    Validating every placement individually must produce exactly what validating the
    timetable produces. If these ever differ there are two implementations behind the solver
    and the interface, which is the thing Decision #5 exists to prevent.
    """
    from tessera.domain.validation import violations_for

    snapshot = snapshot_of(instance)
    # The invariants only. A *hard constraint* also carries weight 0 and is_hard, so
    # filtering on those two would sweep in rules `violations_for` never evaluates.
    whole = {v for v in validate(snapshot).violations if v.rule in INVARIANT_KEYS}
    folded = {
        violation
        for placement in snapshot.placements.values()
        for violation in violations_for(snapshot, placement)
    }

    assert whole == folded


@given(instances(), st.integers(min_value=0, max_value=20))
@THOROUGH
def test_a_move_agrees_with_the_timetable_it_would_produce(instance: Instance, seed: int) -> None:
    """The strongest statement about `validate_move`: asking *would this be legal* must give
    the same answer as making the move and asking *is this legal now*.

    The move check reads the indexes as they stand and filters the moving session out, rather
    than rebuilding them — that is what keeps a drag flat as the institution grows, and it is
    also exactly the shortcut that could quietly answer a different question. This is the
    test that says it does not.
    """
    snapshot = snapshot_of(instance)
    if not instance.sessions or not instance.rooms:
        return

    session = instance.sessions[seed % len(instance.sessions)]
    assert session.id is not None
    room = instance.rooms[seed % len(instance.rooms)]
    assert room.id is not None
    slot = seed % instance.grid.slot_count

    verdict = validate_move(snapshot, session.id, slot, room.id)

    moved = [a for a in instance.assignments if a.session_id != session.id]
    moved.append(
        instance.assignments[0].model_copy(
            update={"id": None, "session_id": session.id, "start_slot": slot, "room_id": room.id}
        )
        if instance.assignments
        else _placed(session.id, slot, room.id)
    )
    after = validate(
        Snapshot.of(
            grid=instance.grid,
            sessions=instance.sessions,
            rooms=instance.rooms,
            groups=instance.groups,
            assignments=moved,
            unavailability=instance.unavailability,
            constraints=instance.constraints,
            course_of=instance.course_of,
        )
    )
    # What `validate_move` claims to answer: the invariants about this session, plus the
    # hard placement rules that *name* it.
    #
    # "Violations mentioning this session" is the wrong lens for the second half. A rule of
    # the form "all of these must share a room" hangs its complaint on the lowest-id session
    # in the set, which need not be the one being dragged — so the rule is selected by what
    # it is about rather than by where it happened to be reported.
    named_by = {
        c.kind.value
        for c in instance.constraints
        if c.enabled and c.is_hard and c.kind in ON_A_MOVE and session.id in c.target_ids
    }
    about_it = {
        v.rule
        for v in after.violations
        if v.is_hard
        and (
            (v.rule in INVARIANT_KEYS and session.id in {v.session_id, v.conflicting_session_id})
            or v.rule in named_by
        )
    }

    assert {v.rule for v in verdict.violations} == about_it
    assert verdict.legal == (not about_it)


def _placed(session_id: SessionId, slot: int, room_id: RoomId) -> Assignment:
    return Assignment(session_id=session_id, start_slot=slot, room_id=room_id)
