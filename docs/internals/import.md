# Importing a spreadsheet

Every real project starts as somebody's spreadsheet. Nobody hand-types two hundred rooms,
and an importer that fails halfway with no explanation is where most tools lose their
users — so this one is built around being **wrong out loud**: it reports before it writes,
names the row and column of every problem, and never quietly fixes anything.

## Two steps, one code path

```
POST /imports/spreadsheet?dry_run=true    →  a report. Nothing is written.
POST /imports/spreadsheet?dry_run=false   →  the same work, and the savepoint is kept.
```

A dry run parses, detects, maps, resolves every reference, validates every row and
**performs every write** — then rolls back. The only difference between the two calls is
whether the savepoint is released.

That matters more than it sounds. A dry run that checked less than the commit would be
worse than no dry run at all, because it turns "I checked" into confidence nobody earned.
Running the same path is how the report becomes a promise: a name already taken is a rule
only the *project* knows, and the dry run catches it because it genuinely tries.

## Three layers, and one of them cannot reach the database

```
tessera/importers/     sheet.py → detect.py → plan.py     no SQLAlchemy, ever
tessera/repository/    imports.py                          catalogue + apply
tessera/api/           routers/imports.py, console/imports.py
```

The boundary is a contract written in 1.2 and enforced by import-linter:

```toml
name = "Exporters and importers are standalone"
forbidden_modules = ["fastapi", "starlette", "sqlalchemy", "ortools"]
```

So the importer cannot write. It reads a file and produces **a plan** — domain objects it
would create, and problems it found — and something else applies it. What that buys:

- the parser can be tested exhaustively against fixture files with nothing running
- a bad import cannot half-write anything by accident, because the half that parses has
  no way to write at all
- the same plan can be built against a hypothetical project in a test, by handing it a
  `Catalogue` nobody stored

## pandas reads the file and interprets nothing

pandas is used for what it is genuinely better at: encodings, byte-order marks, delimiter
sniffing, workbooks. It is given no opportunity to do anything else.

```python
pd.read_csv(..., dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8-sig")
```

Left alone it is eager to help, and every act of help destroys information this phase
exists to report:

| Left to pandas | What the report could then say |
|---|---|
| `forty` in a capacity column becomes `NaN` | "missing" — both wrong and unactionable |
| a room genuinely called `NA` becomes blank | that the row has no name |
| one empty cell makes a column of codes floats | `0101` is now `101.0` and matches nothing |

Two more that only appear on real files. Excel's "CSV UTF-8" export writes a byte-order
mark, and without `utf-8-sig` the first header is `﻿Name` — matching no field, so a
perfect file looks like it has the wrong columns. And a row with fewer cells than the
header is padded with float `NaN`, which through `str()` becomes the string `"nan"` and
then reads as a building nobody can find.

**Row numbers are spreadsheet row numbers** — one-based, header counted. `row 14` has to
mean row 14 in the file somebody opens in Excel. pandas counts its own rows from zero, and
using that would make every message in the report quietly, unfalsifiably wrong.

## Guessing, and admitting it

Real files are not written to a schema. The same column is `Room`, `Room name`, `room_no`
or `Code` depending on who typed it, so both the kind of sheet and the column mapping are
guessed — and both are **reported and overridable** rather than applied silently.

Shapes are scored by how many of their *required* fields match before total matches. That
is what stops a room sheet with a `Department` column being read as a course sheet
because both have a name.

The console renders the mapping as a dropdown per column, including the ones it did not
recognise. Without that, a sheet whose header says something unexpected could only be
imported by editing the spreadsheet — the manual work the feature exists to remove.

## Validation belongs to the domain

The importer does not restate any rule. A capacity cannot be negative and a course needs a
code, and the domain objects already know that, so each row is offered to the entity it
claims to be and whatever it objects to becomes a problem against that row.

A second copy of those rules here would be a second copy to keep in step — the drift
[ADR-0004](../adr/0004-one-validator.md) exists to prevent.

## Suggestions are shown, never taken

```
row 41, features: No equipment called 'projecter'.   Did you mean “projector”?
```

Offered with `difflib`, and never applied. An importer that silently corrects `projecter`
will one day silently merge two genuinely different rooms, and nothing in the file or the
log will say which import did it. Something resembling nothing at all gets silence rather
than the nearest available name, because a suggestion against every problem is a report
people learn to skim.

## What "no partial write" actually means

The exit test asks for two things that pull against each other — *"malformed rows are
rejected"* and *"no partial write"* — so the two are separated:

| | |
|---|---|
| a row fails **validation** | it is not part of the import; the rest still go in |
| a row fails to **write** | the entire import is rolled back |

A file of 200 rooms with three typos imports 197 and names the three. Refusing all 200 is
how an importer gets abandoned in favour of typing the data in by hand. But a write
failure — a rule the dry run could not foresee — takes everything with it, so the project
is never left holding half a file.

**The rollback is a `SAVEPOINT`, not the session's transaction.** `session.rollback()`
would also undo whatever the caller had done earlier in the same request, which for a dry
run means a read-and-report could silently discard someone else's unsaved work. Scoping it
is what makes "roll back" mean "roll back *this*".

## Every row is written through the repository

Not bulk inserts. `create_room` is the only place the rule *"a room called LH-201 already
exists here"* exists for a room with **no building** — SQL treats each null as distinct, so
the unique constraint cannot reach it.

The backlog entry from 2.1 predicted this precisely:

> *"anything writing these without going through the repository — the importer in 2.6 is
> the obvious candidate — would bypass the only guard."*

Bulk inserts would be faster. A few hundred rows once per project is not where speed
matters, and the cost would be a second implementation of every integrity rule, in a
package explicitly forbidden from importing the layer that owns them.

## Two things that only came up on real files

**A group sheet contains the intake and its batches.** Resolving parents only against what
the project already holds would reject every child in the commonest file there is. An
unresolved parent that another row of the same file defines is carried as
`Prepared.pending_parent`; one that nothing defines is still a problem. `_ordered` writes
parents first, and a cycle typed into a spreadsheet keeps its file order and is refused by
the domain, which is the right place for it.

**`term_id` names an institution, not a scope.** Rooms and staff are not term-scoped — but
a project file can hold more than one institution, and `Block A` at one is not `Block A`
at the other. Resolving names across the whole file would silently attach a room to a
building at a different university.

## Packaging

pandas is by far the largest thing this project freezes: the disk image went from 26 MB to
42 MB, accepted deliberately. The pieces it reaches for by string at runtime — the csv and
excel readers, and openpyxl beneath the latter — look to static analysis like nothing
imports them, so they are declared in the spec.

A build without them succeeds and fails on the first upload. So `smoke-test.sh` posts a
spreadsheet to the **installed app** and checks the response, which is the only place that
class of bug is visible before a user finds it.

## Files

| | |
|---|---|
| [`importers/sheet.py`](../../tessera/importers/sheet.py) | reading, and refusing to interpret |
| [`importers/detect.py`](../../tessera/importers/detect.py) | which kind of sheet, which column is what |
| [`importers/plan.py`](../../tessera/importers/plan.py) | rows into domain objects, or into problems |
| [`repository/imports.py`](../../tessera/repository/imports.py) | the catalogue, and applying a plan |
| [`api/routers/imports.py`](../../tessera/api/routers/imports.py) | the two-step endpoint |
| [`api/console/imports.py`](../../tessera/api/console/imports.py) | upload, report, correct, commit |

## See also

- [The browser console](console.md) — where a person actually does this
- [Structural data](structure-crud.md) — the rules every imported row is checked against
- [Student groups](student-groups.md) — why a parent has to exist before its children
- [Packaging and the sidecar](packaging.md) — what has to travel for any of this to work
