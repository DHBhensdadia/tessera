# Domain model

The entities a timetable is built from, and the four shapes that everything else
depends on. This is the layer most expensive to change later, so the reasoning is
recorded here rather than left in the commit history.

## Where things live

| | |
|---|---|
| `tessera/domain/` | Pure Pydantic. No SQLAlchemy, no FastAPI, no OR-Tools |
| `tessera/repository/models.py` | SQLAlchemy mapping — a **separate** set of classes |
| `tessera/repository/mappers.py` | Translation between the two |
| `tessera/repository/migrations/` | Alembic |

Two model sets is deliberate ([ADR-0003](../adr/0003-framework-free-domain.md),
[ADR-0006](../adr/0006-sqlalchemy-over-sqlmodel.md)). The domain can be used by the
solver, the exporters and the CLI without dragging a database along, and the storage
layout is free to differ from the in-memory shape.

The cost is real: a field added on one side and forgotten on the other loses data with
no error anywhere. `tests/repository/test_roundtrip.py` exists to make that loud, and
was itself checked by breaking a mapper and confirming the test failed.

## 1. Time is an integer, never a timestamp

A week is `days × slots_per_day` consecutive integers. A session occupying four slots is
`[start, start + 4)`. Overlap detection is integer comparison.

`TimeGrid.span()` refuses three things a plain `range()` would allow:

- running off the end of the week
- **crossing midnight into the next day** — slot 15 + 2 is not slot 16 on Monday
- **running through a break** — a two-hour lab cannot straddle lunch

Expressing that once here means neither the solver nor the UI has to remember it.

Wall-clock times are derived for display and never stored on an assignment. **Slot
indices are meaningless without their grid**: index 2 is 10:00 on a 30-minute grid and
09:30 on a 15-minute one. That is why the grid is fixed per term and duplicating a term
copies it — editing one term's structure must not silently reinterpret another's stored
assignments.

See [ADR-0005](../adr/0005-integer-slot-grid.md),
[ADR-0014](../adr/0014-slot-granularity.md).

## 2. Groups are a tree, and electives are not

A lecture for an intake conflicts with a lab for one of its sub-batches, because the
same students sit in both. A flat list of groups cannot express that and breaks at the
first lab split.

Electives break the tree in the other direction: "Machine Learning" draws from three
intakes at once and is nobody's child. Modelling it as a tree node would be a lie, so
`GroupKind.COHORT` names its constituent groups explicitly.

Both reduce to one question — *do these two groups share students?* — answered by
comparing leaf sets:

```
conflict(a, b)  ⟺  leaves(a) ∩ leaves(b) ≠ ∅
```

Ancestry falls out for free: an intake's leaf set contains its sub-batches'. `GroupSet`
resolves this once at load and materialises `conflict_map`, so the solver builds
constraints from lookups rather than recomputing intersections in its inner loop.

`GroupSet` rejects unknown parents, unknown members, duplicate ids, cohorts drawing from
cohorts, and **cycles** — a looping parent chain would make leaf resolution
non-terminating, and the tree comes from user data.

## 3. Rooms advertise capabilities, not a type

`Room.features: frozenset[FeatureId]`, matched by subset against
`Session.required_features`.

`room_type: enum` works until the first room that is a chemistry lab *and* has a
smartboard, and then every new category is a migration. Sets scale without one.

## 4. A course is split three ways

| | |
|---|---|
| `Course` | Catalogue entry. Outlives any term |
| `Offering` | That course being taught in one term |
| `SessionTemplate` | A weekly pattern: "3 one-hour lectures to the intake" |
| `Session` | **One teachable block — the atom the solver places** |

Templates are an authoring convenience; expanding one produces the sessions. A template
marked `split_per_attendee` generates parallel sessions per sub-batch, which is how "one
lab, split three ways" becomes three placeable things.

`Session` copies `duration_slots`, `kind` and its requirements rather than reading them
through the template, because a session is the scheduled reality: editing a template
afterwards must not silently alter timetables already built from it.

## 5. Constraints are data

The rules that make a timetable *valid* — no instructor in two rooms at once, capacity,
features, availability — are **not stored**. They are unconditional, and a timetable
violating one is not worse, it is invalid. They live in the validator and the solver.

Everything else is a row: a discriminator, an optional target set, a hard/soft flag and
a weight, following the ITC-2019 formulation. A *global* constraint is a term-wide
preference and names no targets; a *targeted* one applies to specific sessions.

That generality is what lets a new rule arrive as a new handler rather than a schema
migration — and it is why institution-specific quirks could safely be left undecided
while the schema was designed.

## 6. Three fields that had to exist from the first migration

Retrofitting any of these would mean reworking code built on top.

**`Assignment.is_pinned`** — a placement the user chose and the solver must respect.
Without it, re-optimising destroys hand-made edits and the application feels hostile.
One boolean, and it is what makes "pin what matters, rebuild the rest" possible.

**`Timetable.status` + `parent_id`** — a term holds many timetables, not one. Generating
several candidates, comparing them, and publishing the chosen one all depend on this.

**`Command`** — every mutation recorded rather than applied and forgotten. Undo, redo,
the audit trail and "what changed since we published" all fall out of the same rows.
`before` and `after` are both stored so neither direction recomputes state that may
since have changed.

## Integrity the database enforces

Three rules are held by constraints rather than by convention, because all three were
demonstrated breakable while they rested on convention alone. `tests/repository/
test_integrity.py` re-checks each.

**A timetable cannot hold a session from another term.** `session` and `assignment`
both carry `term_id`, and composite foreign keys tie an assignment's session and
timetable to the same one. `session.term_id` is itself tied to its offering's term, so
the denormalised copy cannot drift. Term duplication is where the mismatch would
otherwise occur, and the solver would then produce nonsense from data that looked valid.

**Unavailability names a real subject.** Two nullable foreign keys — `instructor_id`
and `room_id` — with a check constraint that exactly one is set. The obvious
alternative, a `kind` discriminator beside an untyped `subject_id`, cannot be given a
foreign key at all: deleting an instructor left their unavailability behind, and a later
instructor reusing that primary key would have silently inherited it.

The wire format still exposes `kind` and `subject_id`, derived. That the storage could
change without touching the published contract is exactly what separate wire models buy.

**A solve can record what it replaced.** `Command.before` and `after` are free-form
JSON. They were briefly typed `dict[str, int]`, which made `CommandKind.SOLVE` —
documented as undoable — impossible to record, since a solve replaces every placement in
the timetable. The domain was narrower than the column storing it.

## Working with migrations

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # after changing models.py
uv run alembic downgrade base                        # roll back
```

The database URL is supplied at runtime, not read from `alembic.ini` — a project is a
file the user chose the location of. Pass `config.attributes["database_url"]`, or set
`TESSERA_DATABASE_URL`.

**Batch mode is on for SQLite.** SQLite cannot `ALTER` most things, so Alembic rebuilds
the table around the change. Without it, no schema change could be applied to an
existing project file — only to a fresh one. The naming convention in `models.py` exists
for the same reason: SQLite cannot alter an *unnamed* constraint, so anonymous ones
would be undroppable later.

**`env.py` commits explicitly after migrating**, and that line is load-bearing. SQLite
reports non-transactional DDL, so Alembic opens no transaction of its own: the
`CREATE TABLE`s autocommit but the `INSERT` stamping `alembic_version` does not. Without
the commit the schema exists while the database still claims to be at base — the next
downgrade silently does nothing and the next upgrade fails on tables that already exist.
`test_the_cycle_can_be_repeated` covers exactly this.

`test_models_and_migrations_have_not_drifted` fails if `models.py` changes without a
migration. That mistake is otherwise invisible locally, because the test database is
built from the models rather than from the migrations.
