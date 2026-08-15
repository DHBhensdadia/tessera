# Constraints

Two kinds of rule live in this system and only one of them is stored.

The rules that make a timetable *valid* — no instructor in two rooms at once, capacity,
required equipment, availability — are unconditional. A timetable that breaks one is not
worse, it is invalid. They are not rows, because there is nothing to configure: they live
in the validator and the solver model.

Everything else is a row, and this is that layer.

## A rule is a record, not a class

Following ITC-2019's formulation (Decision #12): a discriminator, a target set, a
hard/soft flag, a weight and a small parameter bag.

```
constraint         kind, is_hard, weight, params, enabled, term_id
constraint_target  constraint_id, target_kind, target_id
```

The promise this shape makes is that **adding a rule is a handler, not a migration**.
That promise was not kept until 2.8 — not because the schema was wrong, but because
nothing was required of a kind. Two parallel dicts said which kinds were global and which
took parameters, and a kind absent from both was perfectly legal. Nothing anywhere said
what a kind could be *attached* to, so `RESPECT_INSTRUCTOR_PREFERENCES` over a **room** was
accepted and stored, and would have reached the solver as a rule about nothing.

So "one entry" was true in the useless direction: adding a kind was easy because nothing
checked it.

## The registry

`SPECS` is one entry per kind, and it is the whole of what a kind declares:

```python
class ConstraintSpec:
    scope: ConstraintScope  # may this apply term-wide?
    targets: frozenset[TargetKind]  # what it may be attached to
    params: Mapping[str, ParamSpec]  # name -> label, minimum, maximum, default
    summary: str  # "Give {targets} at most {slots} hour(s) in a row"
```

`test_every_kind_has_a_spec` iterates the **enum**, not the table, so a kind added without
an entry fails rather than behaving like a kind with no rules. And
`test_a_kind_is_unusable_without_its_registry_entry` removes one to prove the entry is
load-bearing rather than decorative — every rule a constraint is held to is reached
through the spec.

**What a spec deliberately does not contain is how to evaluate the rule.** That is Phase
4.1, and P5 requires it be written as an *independent* reading of the same rules: Phase
0.1 got zero cost mismatches across 21 instances precisely because the solver model and
the validator were two separate readings, and sharing logic would let one misreading hide
inside both. A spec is everything else a kind needs.

The `summary` is here rather than in a template because the console needs a sentence per
constraint, and a second copy of the phrasing would drift from the rule it describes.

## Scope means *may*, not *must*

Until 2.7b a constraint could only name sessions, so *"Prof. Shah may teach at most 3
consecutive hours"* could not be written at all. 2.7b made the target polymorphic — and
that turned out not to be enough, because `LIMIT_CONSECUTIVE_SLOTS` was a `GLOBAL` kind
and global kinds were forbidden targets outright. The schema could hold the case and the
domain still refused it.

| | |
|---|---|
| **no targets** | the term-wide preference — and **cannot be hard**, because nothing satisfies "minimise gaps" absolutely; there is no timetable it would accept |
| **targets** | the same preference narrowed to a resource, and it *may* be hard: "at most 3 in a row" is a rule an institution can insist on |
| **`TARGETED` kinds** | meaningless untargeted; "these two must not overlap" needs to know which two |

Decision #80. Every constraint that existed keeps its meaning, because a preference with
no targets is exactly what it always was.

## Targets carry no foreign key

No column can point at sessions, instructors, groups, rooms and courses at once. That is
the price of letting a rule name any resource, and it is paid where every other reference
is checked — `mappers.TARGET_MODELS`, and `_check_targets_exist` in the repository, which
reports the missing ids against the field that named them.

One thing the schema cannot express at all: **a session target must belong to the
constraint's own term.** `target_id` has no foreign key and could not carry a composite
one anyway, so `_reject_targets_from_another_term` is the only check there is. Without it
a rule over another term's sessions stores cleanly, matches nothing the solver places, and
reads as a rule that simply does not work.

Instructors, groups, rooms and courses are *not* term-scoped, by design — outliving a term
is what makes them reusable across one.

## `target_ids` survives as a derived property

The 1.4 contract froze `target_ids: list[int]`, from when a constraint could name sessions
and nothing else. It is kept, because removing a field breaks every consumer, and it is
still the shorter way to say the commonest thing.

It is **derived** rather than stored — the session-kind targets, filtered — so the two
cannot disagree. A group whose id happens to match a session's cannot leak through it and
be read as a session.

The wire mirrors that exactly: `targets` is the general form, `target_ids` the shorthand,
and **sending both is a 422**. Merging them would make "clear the targets" ambiguous under
PATCH, where an empty `target_ids` beside a populated `targets` has no single reading.

## A domain refusal is a 422, not a 500

`Constraint` is a Pydantic model, so a bad rule raises `ValidationError` — a `ValueError`,
but not a `RepositoryError`, so it escapes every caller and becomes a 500. Exactly the
fault Decision #68 fixed for student groups, found again here by a test asserting 422 and
getting a stack trace.

`_rule()` wraps construction and raises `RuleViolationError`, which is distinct from
`ConflictError` on purpose:

| | |
|---|---|
| `ConflictError` → 409 | the **state** forbids it — a name is taken, something still depends on it |
| `RuleViolationError` → 422 | the **request** is wrong — a rule cannot target what it names, a parameter is out of range |

Nothing about the stored data has to change for a 422 to become a 200; the caller has to
send something else. The frozen contract documents 404, 422 and 501 on these routes and no
409, which is the same conclusion reached from the other direction.

## Editing is re-validated as a whole

`update_constraint` rebuilds the domain object rather than assigning field by field,
because every field here interacts with another. Dropping the targets from a hard
preference leaves it term-wide *and* hard — a state neither field is wrong on its own —
and changing the kind changes which parameters are required. A partial edit has to be
checked as a whole or it is not checked.

## A term arrives with opinions

`default_constraints()` has existed since Phase 1.3 and was called by **one test and
nothing else**, so every term ever created started with no preferences at all: the solver
would have had nothing to optimise and the sliders nothing to slide.

`create_term` now seeds them, in the repository rather than the API so importing and
cloning get it too. The weights encode R1 §3's emphasis — student time above staff
convenience, cosmetic preferences low enough to break ties rather than drive the solution
— and every one is editable and removable, which is the entire point.

**A cloned term will copy what its parent had rather than being re-seeded** (2.9). Carrying
the tuning forward is what cloning is for.

## Availability is three-state, and the split matters

Time *preferences* were routed to this phase by Decision #45 on the reasoning that a
weighted preference is a constraint. Decision #78 overruled that in 2.7b: `is_hard` and
`weight` went on `unavailability`, because free / would rather not / cannot is how people
describe their own week.

The consequence was not free. `blocked_slots` is documented as "the set the solver asks
for", and it returned **every** row — so the moment a soft row could exist, it reported
"would rather not" as "cannot", handing the solver a preference dressed as a prohibition.
Invisible in the output, and wrong.

```python
blocked_slots(...)  # is_hard, and only is_hard — narrows the solver's domain
discouraged_slots(...)  # the rest, mapped to weight — adds to its penalty
```

Two functions rather than one with a flag, because the two are consumed differently and
merging them is the exact mistake the split exists to prevent.

The grid renders one `<select>` per cell rather than two checkboxes. Three states is what
availability actually has, and a pair of boxes can express a fourth that means nothing.

## The console

An API-only constraint layer is a preference nobody can express an opinion about. R1 §3's
argument for storing weights as data is that exposing them *"turns 'your algorithm is
wrong' into 'move this slider'"* — which is only true if the slider exists.

Session-level distribution rules are deliberately **not** offered on the page. They are
written against specific sessions, which are generated rather than authored, so picking
two out of several hundred from a flat list would be worse than useless. That belongs to
the timetable view in Stage 5, where a session is something you can point at.

## Files

| | |
|---|---|
| [`domain/constraints.py`](../../tessera/domain/constraints.py) | the record, the registry, and every rule about one |
| [`repository/constraints.py`](../../tessera/repository/constraints.py) | storage, target checking, and the term's defaults |
| [`api/routers/rules.py`](../../tessera/api/routers/rules.py) | both spellings of a target set |
| [`api/console/rules.py`](../../tessera/api/console/rules.py) | the page, and the sliders |
| [`repository/people.py`](../../tessera/repository/people.py) | `blocked_slots` / `discouraged_slots` |

## See also

- [The domain model](domain-model.md) — why a target is a kind and an id
- [The browser console](console.md) — how a person reaches any of this
- [The API contract](api-contract.md) — what "additive only" means, and what guards it
