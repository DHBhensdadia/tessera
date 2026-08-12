# Structural data: rooms, instructors and their scaffolding

Institutions, departments, buildings, features and rooms — the records that outlive a
term. Also the phase that sets the shape every other Stage 2 repository copies.

## The layering, concretely

```
routers/structure.py    translate the wire model, call the repository, translate back
repository/structure.py decides things; owns the rules
domain/entities.py      what a Room is, and what it can host
```

**Handlers contain no decisions.** Anything that chooses, checks or refuses lives in the
repository — because the CLI and the importers call it too, and a rule enforced in an
HTTP handler is a rule the importer does not have.

### Repository functions, not classes

```python
def create_room(session: DbSession, *, name: str, capacity: int, ...) -> d.Room
```

The session is **passed in, never owned**. The API opens one per request and commits it
once; a repository that managed its own would commit halfway through a request that
later fails, leaving a partial write behind.

Domain objects go out, **never ORM rows**. A row handed upward is a lazy-loading failure
waiting for the session to close.

### Errors are the repository's own

`NotFoundError`, `ConflictError`, `InvalidReferenceError` — not `HTTPException`. Status
codes mean nothing to the CLI or an import report, and raising FastAPI's exception here
would drag the web framework into a layer [ADR-0003](../adr/0003-framework-free-domain.md)
keeps free of it.

The API translates them once, in `api/errors.py`. `IntegrityError` is mapped there too:
a duplicate name is the caller's mistake, so **409, not the 500** the catch-all would
otherwise produce.

`ConflictError` carries a count of what is blocking:

```
cannot delete: {"assignments": 18}
```

"Cannot delete" is an error a user can only report. "Used by 18 assignments" is one they
can act on.

## Room filtering

`GET /api/v1/rooms?min_capacity=40&feature_id=3&feature_id=7`

Capacity is a comparison. Features are the interesting part: the question is *rooms
providing **at least** these*, which is relational division — SQL has no operator for it.

```python
query.join(room_feature)
     .where(room_feature.c.feature_id.in_(wanted))
     .group_by(Room.id)
     .having(func.count(func.distinct(room_feature.c.feature_id)) == len(set(wanted)))
```

Join, keep only the wanted features, group by room, and keep rooms whose distinct match
count equals how many were asked for.

The alternative — one `EXISTS` subquery per feature — reads more plainly but grows the
query with every feature. This stays one statement for one feature or six. `set()` on
both sides is what makes a repeated feature id harmless.

**`Room.can_host` in the domain expresses the same rule.** The solver uses one and the
room picker the other, so if they disagree, a room offered in the interface gets rejected
by the solver. A test asserts they agree on every room.

## PATCH means partial

```python
repo.update_room(db, room_id, changes=payload.model_dump(exclude_unset=True))
```

`exclude_unset` reports **only the fields the client actually sent**. That is what
separates *"leave the building alone"* from *"clear the building"* — both arrive as
`None` in a plain read of the model, and a `if value is not None` check silently makes
the second impossible.

## Name uniqueness, and the one gap

| Scope | |
|---|---|
| Room | unique per **building** — two buildings routinely each have a "Room 101" |
| Building, feature, department | unique per **institution** |
| Institution | globally unique |

**Rooms with no building are the gap.** `building_id` is nullable, and SQL treats `NULL`
as distinct from `NULL`, so the constraint cannot reach them. The repository check does —
SQLAlchemy renders `== None` as `IS NULL` — so this case is guarded by **one layer rather
than two**.

`test_the_database_alone_would_allow_it` exists to prove that. If someone later removes
the repository check believing the constraint covers it, that test says otherwise. The
importer must not become the first thing to write rooms without going through this
module.

## Deletion rules

| | |
|---|---|
| Room in use by an assignment | **refused**, naming the count. `ON DELETE RESTRICT` is the backstop |
| Feature used by a room or session | **refused**, naming both counts |
| Building with rooms | **allowed** — rooms survive unattached |

That last one is deliberate. `room.building_id` is `ON DELETE SET NULL`, so removing a
building leaves its rooms without an address rather than deleting them. Losing a hundred
rooms because a building was removed is a far worse outcome than a hundred rooms briefly
lacking a location.


## Instructors

The same pattern as rooms, with one difference worth knowing: **names are unique per
department, not per institution.** Two departments can each employ a different
A. Sharma, and refusing the second would be wrong.

Deleting an instructor who is still assigned to sessions is refused, naming the count.
Their availability is *not* — those rows describe the instructor and mean nothing
without them, so they cascade.

Load limits (`max_slots_per_day`, `per_week`, `max_consecutive_slots`) are stored here
and consumed by the solver in Stage 4. `None` means unlimited. They are soft: an
over-committed instructor should produce a warning, not an unsolvable term.

## Availability

Blocked slots live one row per slot. A busy week is a few dozen rows, and rows can carry
a reason and be explained in the interface — neither of which a packed bitmask allows.

**The interaction drives the design.** Availability is edited by dragging across a grid,
so the real operations are *block a range* and *unblock a range*:

```
POST   /terms/{id}/unavailability          {"kind", "subject_id", "slots": [...]}
DELETE /terms/{id}/unavailability?kind&subject_id[&slot&slot…]
```

One request per cell would mean dozens per gesture.

Three rules follow from that:

**Blocking an already-blocked slot is a no-op**, not a conflict. Dragging across a
partly-blocked range is ordinary use, and failing halfway through a gesture would be
worse than useless. The unique constraint stays as the backstop.

**`slot` on the DELETE is optional.** Omitted, it clears everything for the subject —
the endpoint's original meaning. Given, it frees only those, which is what dragging over
blocked cells to release them actually needs. Added in 2.2; the contract had no way to
express it, so the grid could block and never unblock.

**Slots are checked against the term's grid.** Blocking slot 9999 in a fifty-slot week
would otherwise be stored, ignored by the solver and displayed nowhere — a silent no-op
with nothing for the user to debug.

### The wire shape outlived the storage

The API still speaks `kind` + `subject_id`. Underneath, the 1.3 corrective pass replaced
those with two nullable foreign keys under a check constraint, because a `kind`
discriminator beside an untyped id cannot be given a foreign key at all.

`kind` and `subject_id` are now **derived**, and the published contract never moved.
That is the concrete payoff of keeping wire models separate from domain models
([ADR-0006](../adr/0006-sqlalchemy-over-sqlmodel.md)): a storage change did not become a
breaking API change.
