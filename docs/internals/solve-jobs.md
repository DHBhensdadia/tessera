# Solve jobs

How a term stored in a project file becomes a timetable stored in the same file, and what a
person watching is told while that happens. Three pieces: a loader, a registry, and six routes.

Solving itself is [Solving](solving.md); this is the half-inch of pipe on either side of it.

## The shape of it

```
POST /terms/{id}/solve
   │
   ├─ repository.snapshot.load ──► Snapshot          on the request thread, 27–37 ms
   │      (404 if the term is not there, 409 if the seed belongs to another term)
   │
   ├─ Registry.start ──► 202 { job_id }              one at a time, 409 otherwise
   │        │
   │        └─ a worker thread ──► solver.solve(on_progress=…, stop=…)
   │                                    │
   │              job.status ◄──────────┘            replaced, never edited
   │                    │
   │                    └─ repository.timetables.record   once, at the end
   │
   ├─ GET /solve/{id}/stream ──► an event every 250 ms, reading job.status
   ├─ POST /solve/{id}/cancel ──► Stop.request(), 204
   └─ GET /solve/{id}/result ──► the infeasibility report, where one was proven
```

## 1. Reading a term

`repository/snapshot.py` is the only thing that turns stored rows into a `Snapshot`. Until 4.7
nothing did: the validator had taken one since 4.1, the model since 4.2 and the pre-flight since
4.6, and the only things that ever built one were the tests and the benchmark reading a
competition file. The engine had a solver and no way to point it at the open project.

**It runs on the request thread**, and that is a choice the numbers support: 27 to 37 ms at
department scale, 278 to 304 ms at NFR-9's ceiling. Cheap enough that a term which cannot be
loaded fails as a 404 or a 409 rather than as a job that starts and immediately dies.

**Which rooms belong to a term is 2.6's rule applied again.** A project file can hold more than
one institution, and rooms reach one through a building — an optional link. A room whose building
names another institution is excluded; a room with no building is kept, because there the chain
is broken and the question cannot be answered. Groups stay project-wide, as `imports.catalogue_for`
leaves them, because a `GroupSet` has to be whole for its tree to resolve.

**A seed timetable is what makes re-optimising *re*-optimising.** Its placements arrive as the
term's own, so `Formulation.hint` hands them to CP-SAT as a starting point and `model._pins`
fixes the pinned ones outright. `respect_pins=False` keeps the warm start and drops the pins,
because the two are separate on the wire and the only other way to unpin for one solve would be
to unpin in the data.

## 2. Running one

`api/jobs.py`. [ADR-0008](../adr/0008-in-process-jobs.md) settled the shape in August; what it
could not settle, because there was no solver yet, is how the three hard parts work.

**The solve runs on a thread, and that was measured rather than hoped.** OR-Tools releases the
GIL, so an asyncio loop beside a running solve ticks at 1.046 ms against 1.023 ms idle. The
Python that builds each round's model does not release it, and even at five hundred sessions the
loop's worst stall is 27.5 ms — the interpreter's switch interval bounds it, so model
construction costs throughput and not latency. A subprocess would have bought nothing and cost a
second copy of a 67 MB library, `freeze_support` under PyInstaller, and a `Snapshot` that has to
be pickled.

**One solve at a time.** One engine, one file, one person; two solves would contend for the same
cores and make both slower than either. The 409 names the job holding the engine so a client can
watch that one rather than guess.

**Sixteen finished jobs are remembered**, so a client that reconnects after the end still learns
what happened. Past that the oldest is forgotten and the answer is 404 — the same answer a
restart gives, which ADR-0008 already accepts.

**The result is written once, at the end**, in one transaction: 15.3 ms for five hundred
placements. Always as a *new* timetable with `parent_id` pointing at whatever it was seeded from,
so re-optimising around somebody's pins leaves what they had where it was.

## 3. Watching one

**The job holds one `SolveStatus` and the worker replaces it — never edits it.** Assigning the
attribute is a single reference swap, so a reader sees either the old reading or the new one and
never a penalty from one solution beside a bound from another. That is what makes fan-out free:
every connected stream reads the same attribute on its own schedule, and nothing needs a queue, a
lock, or `call_soon_threadsafe`.

**The stream ticks rather than being pushed to.** Four times a second, which is slower than the
solver can report — CP-SAT found 24 improving solutions inside one second on a small term — and
faster than a person reads. A fixed cadence puts a ceiling on the rate and a floor under the
silence, and the floor is the half that matters:

| term, 30 s budget | events from `on_improvement` alone |
|---|---|
| 150 sessions, 12 rooms | **1**, at 29.51 s |
| 500 sessions, 40 rooms | 11, the first at 7.93 s |
| `comp02` + Tessera's defaults | **none at all** |

Measured against the shipped engine at five hundred sessions, the stream sends **fifty-four
events in fourteen seconds** on a term whose solver reports one improvement in that window.

Three named events: `status` on every tick, `phase` when the solve moves between them, and `done`
once, last. The first event on connect carries the whole current status, so attaching late — or
reconnecting — starts from where things are rather than from nothing.

**The clock is computed at emit time**, not stored, so a panel keeps counting through a phase the
solver says nothing during. And the phase is named *before* the search starts: the solver's first
progress event is the feasibility pass **finishing**, which at five hundred sessions is seven
seconds in, so a job that took its phase from that event reported `queued` through seven seconds
of real work.

## 4. Stopping one

`Stop` is two mechanisms and neither is enough alone — the argument is in
[Solving §8](solving.md). From the API's side: the route calls `Stop.request()` and returns 204,
the worker unwinds on its own thread, and **whatever was found is kept**. Cancelling is not
discarding; P7 draws `[ Stop ] [ Keep Result ]`, and a stop that threw away forty seconds of
improvement would make that button a trap.

Cancelling is idempotent, including on a job that has already settled. Pressing stop a moment
after the answer arrived is not a mistake worth an error about.

## 5. Refusing

Two routes exist for terms that have no timetable, and they are different strengths of evidence.

`POST /terms/{id}/preflight` runs the counting arguments — arithmetic, no model, about a
millisecond. `can_solve: true` means **nothing here proves this term impossible**, which is
weaker than a promise that it can be solved, and the schema says so: these checks can prove a
term impossible and can never prove one possible.

`GET /solve/{id}/result` is the report for a job that ended `infeasible`, and it answers 409 for
one that did not — an empty report would imply something had been proven when nothing had.
`infeasible` is reserved for a term something has proven has no timetable; a solve that simply
did not find one settles as `done` with no timetable against it. That is #205's distinction
carried onto the wire.

**A term with no sessions is refused before a job starts.** `Solution` forbids a solved timetable
with no placements on purpose (4.1's D6 keeps completeness a separate question), so an empty term
reached that invariant from the wrong side and raised. A term nobody has filled in yet is an
ordinary state on the first day of one, not a failure.

## 6. Where to look when something is wrong

| Symptom | Look at |
|---|---|
| A solve reads the wrong term, or a room from another institution | `repository/snapshot.py` → `load`, `_rooms` |
| Re-optimising starts from nothing | `snapshot.load(seed_timetable_id=…)`; `Formulation.hint` reads `Snapshot.placements` |
| A rule is priced at zero that should not be | `snapshot._course_of` — two of the sixteen need it and `Snapshot` does not derive it |
| A second solve is refused | by design — `Registry.start` raises `AlreadySolvingError`, and the detail names the job |
| A finished job answers 404 | it was forgotten; `REMEMBERED` keeps the last sixteen, and a restart keeps none |
| The panel shows nothing, or stale numbers | `jobs.events` ticks; `jobs.advance` replaces the status rather than editing it |
| The panel says `queued` while the engine works | `Registry._run` names the phase before searching |
| A cancel is answered late | `solver/cancel.py` → `Stop`; a flag alone waits for the running solve to end |
| A job ends `failed` | something unexpected reached `Registry._run`; it is logged with a traceback |
| A half-written timetable | `repository/timetables.py` → `record` writes the whole result or none of it |
