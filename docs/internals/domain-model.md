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

What was missing was not a type but a **number**. A computer lab with thirty
workstations and seventy seats is two different rooms depending on what happens in it,
and a set could only say *has computers* — so nothing stopped sixty students being sent
to thirty machines. `Room.feature_counts` and `Session.required_counts` carry the count
where a count exists; absent means *present, count irrelevant*, because nobody counts
projectors. `can_host` takes the required counts as an optional argument, so a session
that does not count its equipment is still satisfied by presence alone.

`Room.turnaround_slots` is the other half of a room being physical: a chemistry lab
cannot be handed over the instant the previous class ends. Zero for a classroom, hence
the default. Nothing enforces it yet — Stage 4 writes the overlap rule once, against a
model that already knows rooms need clearing.

The convenience a type enum was reaching for belongs in the interface instead: pick
"Chemistry lab" in the console and it applies the feature set, which stays editable and
stays authoritative. That is UI work with no schema risk.

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

Everything else is a row: a discriminator, a target set, a hard/soft flag and a weight,
following the ITC-2019 formulation.

**A target is a kind and an id, not a session id.** That distinction is the whole of
Phase 2.7b. Until then `constraint_target` held `(constraint_id, session_id)`, so
*"Prof. Shah may teach at most 3 consecutive hours"* and *"CSE5-A: no more than two gaps
a day"* could not be written at all — the normal case in a department rather than an
edge case. Three kinds were global-only, meaning they applied identically to everybody
or to nobody, while FET's palette is almost entirely per-resource.

So the generality Decision #12 promised was **false for any per-resource constraint**,
and would have stayed false under everything 2.8 built on it.

```
constraint_target  →  constraint_id, target_kind, target_id
```

`target_id` carries no foreign key, because no column can point at sessions,
instructors, groups, rooms and courses at once. That is the price of the shape; it is
paid where every other reference is checked, in `mappers.TARGET_MODELS`, which fails
loudly on an id that does not exist.

Scope became "may this kind apply term-wide", not "must it":

| | |
|---|---|
| no targets | the term-wide preference it always was — and **cannot be hard**, because nothing satisfies "minimise gaps" absolutely |
| targets | the same preference narrowed to a resource — *may* be hard, because "at most 3 consecutive hours" is a rule an institution can insist on |
| `TARGETED` kinds | meaningless untargeted; "these two must not overlap" needs to know which two |

`Constraint.target_ids` survives as a **derived** property returning only the session
targets, because the frozen API contract speaks in session ids. Derived rather than
stored, so the two cannot disagree — and a group whose id happens to match a session's
cannot leak through it.

That generality is what lets a new rule arrive as a new handler rather than a schema
migration — and it is why institution-specific quirks could safely be left undecided
while the schema was designed.

## 6. A week that is not always the same week

A `TimeGrid` is one repeating week, which cannot say *"this lab runs fortnightly"* —
ordinary practice wherever equipment is shared. `week_pattern` on sessions and templates
is `EVERY_WEEK`, `ODD_WEEKS` or `EVEN_WEEKS`, and the only rule anything needs from it is
`coincides_with`: two blocks can clash only if their patterns can land in the same week.

**Not** ITC-2019's 13-week bitmask. That multiplies the solver's variables by the number
of weeks — which Decision #35 already warns about at department scale — to buy "weeks 3,
7 and 11", which nobody has asked for. FET has no equivalent at all and serves thousands
of schools, so this is a judgement rather than an oversight; the pattern is the cheapest
thing that makes the expensive retrofit unnecessary, and if arbitrary weeks are ever
genuinely needed it becomes a mask without changing anything that reads it.

Retrofitting it later would have touched every assignment, the overlap check, the solver
formulation and the grid. It is the most expensive thing on R5's list to add late, which
is why it is here before anything reads it.

**`Unavailability` is three-state.** `is_hard` and `weight` turn *cannot* into *cannot*,
*would rather not*, and free — which is how people describe their own week, and which
gives `RESPECT_INSTRUCTOR_PREFERENCES` (a constraint kind with no data behind it since
1.3) something to read. Rows written before this are hard, which is the only thing they
could ever have meant.

## 7. Three fields that had to exist from the first migration

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

### Foreign keys are off while migrating, and checked afterwards

Enforcing them during a migration looks like the careful choice and is the opposite of
one.

SQLite has no `ALTER` for a primary key, so any real change means rebuilding the table —
and **with `foreign_keys=ON` a `DROP TABLE` performs an implicit `DELETE FROM` first**,
which fires `ON DELETE CASCADE` into every child. Batch mode rebuilds tables. So adding
one column to `room` silently emptied `room_feature`, and the migration reported success
having deleted every room's equipment.

It passed every migration test at the time, because they all ran against an empty
database. `env.py` now migrates with enforcement off and runs `PRAGMA foreign_key_check`
at the end, failing loudly on anything dangling — SQLite's own documented procedure, and
a stronger guarantee than enforcement-during-DDL: it inspects every row that exists
rather than only the ones a statement touched.

Two things follow for anyone writing a migration here:

- **A migration that has only run against an empty schema is not known to work.** The
  tests in `test_migrations.py` seed a row into every table a revision reshapes, migrate,
  roll back and migrate again. `test_rows_survive_the_tables_being_rebuilt` is the one
  that caught the cascade.
- **Autogenerate does not move data.** Asked to make `constraint_target` polymorphic it
  produced a revision that dropped `session_id` and added `target_id` without copying
  between them — correct in shape, and it would have emptied the constraint targets of
  every project already in existence. Tables that change shape are rebuilt explicitly in
  that revision, with the copy stated column by column.
