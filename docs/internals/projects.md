# Projects and terms

Two things that look like file management and are not: what a `.tessera` actually is, and
what it means to roll a term into the next semester.

## A project is a package, and always was meant to be

```
CSE Timetables.tessera/      <- one item in the Finder
    project.db               <- SQLite
    assets/                  <- room for logos and imported sources
```

This was settled before any code was written: a project is **a real file the user chose
the location of**, not a hidden library entry. Timetables are emailed,
reviewed and archived by committees, and a file uses habits people already have —
Dropbox, Time Machine, "send me the Autumn one". A library model is simpler to build and
worse to live with.

What Stage 1 shipped was a bare SQLite file. The package landed in 2.9, the last phase
before a version tag and before any Swift is written against what a project path means.

**A `v0.1.0` file is converted in place the first time it is opened.** Not refused, not
migrated by prompting — the shape of the container is not something a user asked for or
can act on. The conversion goes through a staging directory and one rename, so a crash
leaves either the original file or the finished package and never a half-built directory
where the project used to be.

**The write-ahead log comes with it.** With WAL, committed rows can still be sitting in
the `-wal` sidecar; moving only the main file produces a database that opens perfectly and
is missing the user's last edits. That is worse than one which refuses to open, because
nobody investigates a file that opened. The test for this holds a connection open on
purpose — closing the last one checkpoints the WAL away, and the first version of that
test passed with the sidecar handling deleted.

Nothing outside `project.py` knows the layout. `--project` still takes one path and still
means "the project".

## There is no open, and no save

| | |
|---|---|
| **open** | The client launches an engine per project. That is what the 1.5 handshake was built for — *"a fixed port … prevents two projects being open at once"* |
| **save** | SQLite commits. P7 Act 12: there is no Save button and no unsaved-changes dialog |
| **save as** | `POST /project/copy` — the one project-level thing the client cannot do for itself |

An open endpoint was considered and rejected. It would make the engine's identity mutable,
invalidate every open session, and give the token a second meaning. The process boundary
is what keeps two projects apart, and it is free.

**Copying is not `cp`.** With WAL the bytes on disk are not the whole database, so a file
copy of a live project gives you one that is quietly out of date or torn between two
states. `VACUUM INTO` takes a consistent snapshot under a read lock and compacts on the
way out, in one statement. `sqlite3.Connection.backup()` is equally correct; the smaller
output settled it, and this is an explicit user action rather than a hot path.

A destination that exists is refused rather than overwritten — `mkdir` without
`exist_ok` *is* the refusal — because "save a copy" onto an existing folder is how
somebody loses the thing they were copying to.

## Duplicating a term

The feature that makes the application worth keeping. The first semester costs a day of
data entry; every one after it should cost an hour.

### Most of the checklist cannot be copied

P7 Act 11 offers seven things to carry over. **Four of them name things that are not
term-scoped** — rooms, instructors, student groups, courses. They hang off the
institution, which is exactly what makes them reusable across terms, so the new term can
see them the moment it exists and unticking a box could not remove them.

So the flags are a *request* and the response is a **receipt**:

| | |
|---|---|
| `copied` | Rows were written: offerings and their templates, constraints, availability |
| `shared` | Not term-scoped; available to the new term without being copied |
| `skipped` | Deliberately left behind |

Echoing the request back would have described an operation that did not run. The console
does not render the four as disabled controls either — a checkbox that cannot be false is
worse than a sentence saying why.

### Sessions are expanded, never copied

`expansion.expand` is the only definition of which sessions a term has. Copying session
rows would be a second one, obliged to agree with it forever — the drift
[ADR-0004](../adr/0004-one-validator.md) exists to prevent — and it would mean remapping
every template id by hand.

So a duplicate copies **offerings and templates**, then runs the expander. The new term
comes out with its own sessions, unplaced, and *"assignments cleared"* is true by
construction rather than by remembering to delete something.

### The tuning is carried, not re-seeded

`create_term` seeds the seven default preferences (2.8, D5). A duplicate goes through
`create_term` — so it gets every rule about names, grids and institutions — and then
**replaces** those defaults with the originals.

This is the trap 2.8 set for 2.9. A duplicate that stopped after `create_term` would look
like it worked and would have discarded every weight the user set, which is the one thing
duplication exists to preserve. Merging instead of replacing would be worse still: two of
each rule, with different weights, and no way to tell which one the solver read.

`is_hard` and `weight` come across on availability too. A soft *"would rather not teach
Friday afternoon"* arriving in the new term as a hard refusal is a rule nobody wrote and
one they would have to hunt down to remove.

**A rule about last term's sessions is dropped, not emptied.** Those rows belong to the
term being copied from. Carrying the ids would point the new rule at another term's
sessions; carrying an empty target set would leave a distribution constraint naming
nothing, which the domain refuses anyway. Rules about people, groups, rooms and courses
carry over intact — which is what a per-instructor limit needs.

### Groups are not advanced a semester

P7's dialog promises *"groups will be advanced one semester where possible"*. It is not
implemented, and the reason is worth stating rather than leaving as a silence.

Groups are not term-scoped. "Advancing" one would rename a row **the original term still
points at**, turning last semester's published timetable into a record of groups that no
longer exist under those names. The feature needs per-term membership or a separate set of
groups — a data model change, not a copy — so it is a backlog entry rather than a quiet
omission.

## Files

| | |
|---|---|
| [`project.py`](../../tessera/project.py) | the package, the conversion, the safe copy |
| [`repository/duplication.py`](../../tessera/repository/duplication.py) | what a term carries forward, and the receipt |
| [`api/routers/project.py`](../../tessera/api/routers/project.py) | Save As, and the two routes that deliberately do not exist |
| [`api/console/calendar.py`](../../tessera/api/console/calendar.py) | the Duplicate page |

## See also

- [The domain model](domain-model.md) — why rooms and staff outlive a term
- [Constraints](constraints.md) — what the weights are, and why they must survive a copy
- [Packaging and the sidecar](packaging.md) — how the engine is handed a project at all
