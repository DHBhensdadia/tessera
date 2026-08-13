# Courses, the calendar, and how a weekly pattern becomes a timetable

What gets taught, when the week is, and how "3 lectures and a lab split three ways"
turns into the six blocks the solver places.

This is the largest subsystem in the data layer, and almost all of its difficulty comes
from one fact: **the same operations are run again after a timetable already exists.**
Every rule below is there because the second run must not destroy the first.

## The three levels

```
Course          CS301 Operating Systems          survives every term
  └─ Offering     CS301 in Autumn 2026-27        one course, one term
       ├─ SessionTemplate   3 × lecture, 2 slots, whole intake
       └─ SessionTemplate   1 × lab, 4 slots, split per sub-batch
             ↓ expansion
           Session × 6                            what the solver places
```

A **course** is a catalogue entry with no term above it — a syllabus committee creates
courses long before anyone decides which semester teaches them. An **offering** is a
course being taught in a particular term. A **template** is a component of the weekly
pattern, and a **session** is one teachable block.

Sessions are *generated*, never authored: there is no `POST /sessions`, and the interface
shows the weekly pattern producing them.

## Time is an integer, and that is why grids are frozen

A slot is an index into the week, never a timestamp (ADR-0005). Slot 40 means
"Tuesday 14:00" only by reference to a grid's `days`, `slots_per_day`, `slot_minutes`
and `day_start_minute`.

Change any of those and **every stored slot in every term on that grid silently means
something else**. Some indices land in a different day, others fall outside the grid
entirely. No error is raised anywhere — every assignment, every blocked slot and every
pinned placement is simply wrong.

So there is no way to edit a grid. Not a `PATCH` route, not an `update_time_grid`
function, and a term cannot be repointed at a different grid either. To change the shape
of the week you create a second grid and build a new term on it; the old grid stays, so
old timetables keep their meaning.

The guard for this is unusual and worth knowing about, because it protects an *absence*:

```python
# tests/api/test_calendar.py
def test_the_contract_offers_no_way_to_edit_a_grid(app: FastAPI) -> None:
    """Fails if PATCH or PUT /time-grids/{id} ever appears in the published spec."""
```

The first version of that test walked `app.routes` — which stores included routers as
opaque objects with no `path`, so the comprehension was always empty and the assertion
always held. It was found by adding the forbidden route and watching the test pass
anyway. It reads the OpenAPI surface now.

## Expansion is reconciliation, not generation

The obvious implementation of "turn templates into sessions" deletes every session for
the offering and recreates them. **That is correct exactly once.**

`session` cascades from `offering` and `assignment` cascades from `session`, so the
second run silently discards a scheduled timetable — including pinned placements, which
are the user's hand-made decisions. Editing "3 lectures" to "4" must add a fourth, not
unschedule the first three.

So each session is matched to the pattern that should have produced it, by a key:

```
(template, attendee set, occurrence)
```

| | |
|---|---|
| key wanted, session exists | **left completely alone** — not even updated |
| key wanted, no session | created |
| session whose key is no longer wanted | removed — unless it is scheduled, in which case the whole expansion is refused |

Running it twice changes nothing the second time, which is what makes it safe to offer
as a button.

### Why matched sessions are never updated

Duration, kind and requirements are *copied* into a session rather than read through its
template, because a session is the scheduled reality: one lab running long is a real
thing to want, and `PATCH /sessions/{id}` exists for it.

Updating on re-expansion would silently revert those deliberate edits. So reconciliation
adds and removes and nothing else — and templates are correspondingly restricted:
`PATCH /templates/{id}` changes **multiplicity only** (`per_week`, `split_per_attendee`,
`attendee_ids`). Shape is fixed at creation, because nothing records whether a given
session diverged, so propagating a shape change could only either overwrite deliberate
edits or leave a component and its sessions disagreeing with nothing to say which is
right. Changing shape means deleting the component and adding it again.

### Why `occurrence` counts within an attendee

Two labs a week across three sub-batches is six sessions, numbered

```
(A1,0) (A1,1)   (A2,0) (A2,1)   (A3,0) (A3,1)
```

rather than a flat 0–5. It reads as "lab 1 of 2 for batch A1", which is what the
interface must show — and it is *stable*. A flat numbering renumbers whenever anything
changes, which would break the very key it forms part of.

### Sessions with no template are never touched

Nothing in the API creates one. But a project file someone has edited by hand can
contain one, and quietly deleting a row this module did not create is the worst available
answer. They are skipped entirely: never matched, never removed.

## The pattern behind every refusal

Almost every delete in this subsystem refuses rather than cascades, and the reason is
always the same shape — **the schema's cascade reaches further than the button implies**:

| Deleting | Refuses while | Because it would otherwise take |
|---|---|---|
| a time grid | any term uses it | the meaning of every slot in those terms |
| a term | it has offerings | every session and assignment in the semester |
| a course | it is offered anywhere | those offerings, their sessions, their placements |
| an offering | it has sessions | the expanded set and anything scheduled from it |
| a template | any of its sessions are **scheduled** | somebody's placed work |
| an institution | anything belongs to it | five cascade chains, i.e. the project |

The cascades stay in the schema as a backstop for paths that bypass the repository —
preventing dangling rows rather than performing the deletion.

Two of these are deliberately *not* symmetric, and both are worth remembering:

- **Deleting a template removes its unscheduled sessions.** They are derived data with no
  independent existence, and removing the component is exactly what the caller means.
  Refusing whenever any session existed would deadlock: sessions are removed only by
  expansion, and expansion reconciles against the templates that exist, so a component
  that had ever been expanded could never be deleted at all.
- **Deleting a department does not block on courses.** `course.department_id` is
  `ON DELETE SET NULL`, and a course with no department is a state the catalogue is
  designed for. Guarding it would make that design unreachable.

## Where the rules live

The domain owns everything that is a *rule*; the repository owns everything that is a
*query*.

| Question | Answered by |
|---|---|
| How many sessions does this pattern produce? | `SessionTemplate.session_count` |
| Can a block this long sit in this week? | `TimeGrid.start_slots_for` |
| Does this session have anyone in it? | `Session._has_attendees` |
| How many students must this room seat? | `GroupSet.leaves_of`, unioned — never summed, or overlapping attendees double-count |
| Do these dates run forwards? | `Term._dates_run_forwards` |

`repository/expansion.py` computes what *should* exist and compares it with what does.
It does not decide what a weekly pattern means — that is
`SessionTemplate.session_count`, and the expansion tests assert the two agree rather
than trusting them to.

## Files

| | |
|---|---|
| [`repository/teaching.py`](../../tessera/repository/teaching.py) | the course catalogue |
| [`repository/calendar.py`](../../tessera/repository/calendar.py) | time grids, terms, offerings |
| [`repository/sessions.py`](../../tessera/repository/sessions.py) | templates and sessions |
| [`repository/expansion.py`](../../tessera/repository/expansion.py) | the reconciliation loop |
| [`api/routers/teaching.py`](../../tessera/api/routers/teaching.py) | the HTTP surface |

## See also

- [ADR-0005](../adr/0005-integer-slot-grid.md) — why time is an index
- [Domain model](domain-model.md) — the entities themselves
- [Student groups](student-groups.md) — the attendees a session is taught to
- [Structural data](structure-crud.md) — rooms and the scaffolding around them
