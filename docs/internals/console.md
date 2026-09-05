# The browser console

A plain HTML interface to the engine, served by the engine itself. It exists so the
backend can be used and checked **by hand**, months before any native client — which
takes Swift off the critical path entirely.

It is deliberately plain. Every hour spent styling it is an hour not spent on the app
people will actually use, and a console that starts looking like a product starts
competing with one.

It is also not throwaway: the same renderer is meant to become the static HTML export and
the Docker-mode web UI. That constrains how the templates are factored — see
[Read and write are kept apart](#read-and-write-are-kept-apart) — but neither is built
here.

## Getting in

Every route is protected by a token the engine generates per launch and announces in its
handshake, so that any other program on the machine can open the loopback port and get
nowhere.

**A browser navigating to a URL cannot set a header.** So the console is entered once
through a link and holds a cookie afterwards:

```
GET /console?token=<from the handshake>   →   303, sets the cookie, redirects to /console/
```

**On that one path the query beats the cookie**, which it did not until 4.8 ran a browser
against a restarted engine. A token is issued per launch, so the previous launch's cookie is
stale — and being read first it shadowed the valid token in the fresh link, answering 401 to
the only URL that could have fixed it. The way out was clearing site data. The order is now
header → query-on-the-entry-path → cookie, which widens what gets *in* on one path without
widening what counts as authentic: a wrong token in the URL is still 401 and a stale cookie
on its own is still 401.

The token appears in a URL exactly once — one entry in browser history rather than one
per page — and the response carries `Referrer-Policy: no-referrer` so it does not travel
onward. This is what Jupyter does, for the same reason.

The query carrier is accepted **on that path only**. Accepting it everywhere would put
the token in history and logs on every request; opening the path instead would mean a
route handing out cookies without checking what it was given. Authentication stays in one
place: the middleware in [`api/app.py`](../../tessera/api/app.py).

### Why the cookie needs two more defences

A cookie is attached by the browser automatically, which is the point and the risk. Any
page the user happens to be visiting could submit a form to
`http://127.0.0.1:<port>/console/…` and the browser would send the session with it.

| | |
|---|---|
| `SameSite=Strict` | the cookie is not attached to cross-site requests at all |
| a `Host` check | closes what `SameSite` cannot see — under DNS rebinding the attacker's own domain resolves to loopback, so the browser correctly considers it same-site |

The host check is middleware rather than a dependency, so it covers routes added later,
and it runs **before** the token check: a foreign host gets `403` without learning
whether a token would have been accepted.

**It covers every path, and until 4.8 it covered only `/console`.** Measured then: with the
session cookie set and `Host: evil.example`, `/console/rooms` answered 403 and `/api/v1/rooms`
answered **200** — the same data on the same socket with one fewer defence. It was not a live
hole, and saying so is part of describing it accurately: the cookie is host-only, so a browser
rebound to an attacker's domain sends that domain's jar and the request arrives with no token
at all. **The token is what stops the attack**; this is the second line, and it now exists on
both paths. It lives in `api/app.py` as `refuse_foreign_host`, because it stopped being about
the console. A deployment binding beyond loopback has to widen `ALLOWED_HOSTS` — Stage 7's
Docker image will, and `engine.main` already warns loudly about the `--host` that gets there.

`HttpOnly` keeps the session out of reach of any script on the page. This is the one
place in Tessera where data becomes reachable from outside a private process, and it is
worth being deliberate rather than lucky about.

## What the console is, architecturally

Handlers call `tessera.repository` **directly**, exactly as the API routers do. They are
two presentations of one set of rules, not two implementations — nothing in
`api/console/` decides anything.

```
api/routers/…  ─┐
                ├─→  repository  →  domain
api/console/…  ─┘
```

Calling its own HTTP API instead would mean a loopback round trip per page and failures
that are hard to attribute. Putting logic in the console would mean a second
implementation of every rule, which is the drift [ADR-0004](../adr/0004-one-validator.md)
exists to prevent.

**One thing is not shared: failure rendering.** The API answers a conflict with an
RFC 9457 document; a person filling in a form needs prose, beside the form, with what
they typed still in the fields. `describe()` in
[`console/base.py`](../../tessera/api/console/base.py) is that translation and the only
thing the console knows that the routers do not.

That difference earned its keep immediately. Reaching the group rules through a form
found that `POST /api/v1/student-groups` had been answering **500** since 2.3 for a
structural group given `member_ids`: the domain raised, but as a pydantic error rather
than a `RepositoryError`, so it escaped every handler. The rule had a test; the *path* to
it did not.

## Declared sections, explicit routes

Institutions, departments, buildings, equipment and programmes are the same form five
times — a name, sometimes a code, sometimes a parent. They are a `KINDS` table in
[`console/places.py`](../../tessera/api/console/places.py) rather than five modules,
because five copies drift: the missing `exclude_id` fixed once in 2.4b would otherwise
have been five separate omissions waiting to happen.

Instructors and student groups are **not** in the table. One owns a week of availability,
the other a tree. The rule is that the moment an entity needs more than a name, a code
and a parent it gets its own module, and the table does not grow a special case.

Their routes are registered **per slug**, not behind a `/{slug}` catch-all. A catch-all
has to come after every bespoke section or it swallows their paths first — which makes
route matching depend on **import order**, and sorting that import alphabetically was
enough to break `/console/rooms` silently, with every other test still green. Behaviour a
formatter can rearrange into a bug is not behaviour worth having.

Navigation comes from `SECTIONS`, injected by `page()`. A section appears in the menu by
existing rather than by being remembered: a page nobody can navigate to is a page that
does not exist.

## Generating a timetable

Added in 4.8. Three pages, and the division between them is the only unusual thing here.

```
GET  /console/terms/{id}/timetables    the candidates, and the form that makes another
POST /console/terms/{id}/generate      pre-flight, then start  →  303 /console/solve/{job}
GET  /console/solve/{job}              where it has got to
POST /console/solve/{job}/stop         →  303 back to the same page
GET  /console/solve/{job}/impossible   the requirement list, when something proved there is none
GET  /console/timetables/{id}          one pivot, one subject
```

**The actions are the console's and the progress stream is the API's.** A form cannot post to
`POST /api/v1/terms/{id}/solve` — it answers 202 with a JSON body, which a browser renders as
text — so there is no way to make the API do post-redirect-get, and the console owns `generate`
and `stop` whatever else is decided. It calls `api.jobs.Registry` directly, not itself over
HTTP. What it does not own is progress: that is `GET /api/v1/solve/{id}/stream`, published in
the contract and the same endpoint the native solve panel will use. Two implementations of one
stream is what [ADR-0008](../adr/0008-in-process-jobs.md) and Decision #304 exist to prevent.

**Every generate runs the pre-flight first**, and *Solve it anyway* is still offered. The
checks are counting arguments — one that fails proves the real problem cannot be satisfied
either — so proceeding is offering to search for something already known not to exist. It is
offered because the search's refusal is more useful than the arithmetic: an `infeasible`
ending carries the minimal conflicting set, and a shortfall carries one subtraction.

### Watching one

**The page is complete without a script**, and the script is what stops it being discarded four
times a minute. Where scripting is off, a `<noscript>` meta refresh brings the next reading;
where it is on, `templates/solve/watch.js` opens an `EventSource` on the stream above and
writes into the markup already there. Measured over a 55-second solve: **two page loads** — the
first, and the reload when it settled — against the 28 the refresh alone would have made.

[ADR-0017](../adr/0017-javascript-in-the-console.md) is the decision and its boundary. Four
things about the script are load-bearing:

* **It carries no template expression.** Starlette's `select_autoescape()` escapes `.html` and
  not `.js`, so a variable written into an included script comes out raw while the same value
  in the page comes out escaped. Everything it needs arrives on `data-` attributes of `#solve`,
  which are autoescaped because they live in the HTML. `tests/console/test_markup.py` asserts
  the rule by looking for Jinja's delimiters in the file.
* **The server keeps the prose.** Every phase's heading and sentence come from
  `console.solving.PHASES`, rendered into a hidden block that the script *selects* from. A copy
  in JavaScript would drift, and a heading left at what the server said on page load is worse
  than either: a term that reaches feasibility in under a second sits under the wrong one.
* **It reloads when the solve settles.** Which ending it was, and whether the budget or the
  arithmetic stopped it, is written once in `wording` — the reload is how those sentences
  arrive rather than a second copy of them living in the script.
* **It closes the stream twice over.** `EventSource` reconnects for ever three seconds after a
  server closes one, and an open stream holds one of the six connections a browser will make to
  an origin over HTTP/1.1 — so it is closed on `done` and on `pagehide`.

**The curve is drawn from what the page has seen, not from the whole solve.** `SolveStatus`
carries no trajectory (#306) and widening it was refused, so a reload honestly starts again and
the caption says so. It stays hidden until two *distinct* penalties exist: a term can hold one
score for twenty seconds, and a flat line along the bottom of an empty box says less than no
box while taking up more room.

**Two 409s are pages rather than errors.** A second Generate redirects to the job that already
holds the engine, because that is what somebody pressing it twice wants; a term with nothing in
it gets a sentence beside the button rather than a traceback (#307).

## Reading a timetable

**One projection, three consumers.** `tessera/export/grid.py` turns a `Snapshot` and a set of
names into `Week`s — rows, cells, and the `span`/`covered` pair that draws a two-hour lab once
across two rows instead of twice. `GET /timetables/{id}/grid` reads the same function, and
6.2's static export will too. It lives in `tessera.export` rather than beside either consumer
because that package is forbidden SQLAlchemy and Starlette, so it is the only one of the three
places the export can reach (#311).

**One subject at a time, and that is a measurement.** A page draws cells, most of them empty,
so its size follows the grid and the number of subjects rather than the number of placements:
every room of a 500-room institution in one page is 1.7 MiB of HTML. Fine at department scale,
fine in every test, wrong only for the largest institutions — the failure
[ADR-0012](../adr/0012-viewport-scoped-validation.md) exists to refuse. The wire is different
and stays different: `GridView` carries placements, so the route serves the whole grid.

**Group weeks are keyed by leaf**, which is the reading the clash rule already uses: a leaf is
the set of students who share a week, so a lecture to an intake appears on every batch's
timetable. Pivoting on the parent would produce a document no student is handed.

**The violation count is the validator's, not the solver's.** `Timetable.penalty` is what the
search said its own answer cost; the number on this page comes from running the 4.1 validator
over the stored placements. Reporting the stored one would make the two indistinguishable, and
agreement between two independent readings is the whole reason the validator was written
separately from the solver.

## The pages that do something interesting

**The availability grid** turns a week of integers back into days and clock times using
the term's own `TimeGrid`, so the labels here and the ones the solver reasons about come
from one place. Breaks are shown and not tickable — seeing lunch in the grid is how
someone confirms the week is the one they meant to set up.

Saving **replaces** the whole week rather than diffing it. An unticked checkbox is simply
absent from the submitted form, indistinguishable from one that was never rendered;
anything other than clearing and re-blocking would silently keep the hour just freed.

**The group tree** is drawn as a nesting because that is what it is. An intake of 120
splitting into three batches of 40 is the reason three labs can run in parallel while a
lecture cannot run opposite any of them, and a flat list hides the only structure worth
seeing. Headcount and clashes are read from `GroupSet` — the object the solver reads — so
the page and the solver cannot disagree.

**The offering page** is what the product is about:

```
3 × lecture, 2 slots, 2024 Intake, Prof. Sharma        → 3 sessions
1 × lab, 4 slots, A1 A2 A3 · split, needs computers    → 3 sessions
```

"→ 3 sessions" makes the lecture/lab-split model visible without documentation. Editing
a pattern changes **no sessions** until *expand* is pressed; until then the page shows
what the pattern would produce beside what it has — `(3 now — expand to reconcile)` — so
the cost of a change is visible before it is paid.

**The teaching-week page has no edit form, and says so.** Every scheduled hour is stored
as a number counted through the week, so changing the shape of one would silently move
everything already placed. An absence with no explanation is one the next person fixes;
the page explains it and offers a second week instead.

## Read and write are kept apart

Tables are rendered from data alone, with no form targets in them. Forms are separate
blocks below. The reason is the static HTML export this renderer is meant to become — an
export has no server to post to — and it costs nothing now.

Values are escaped, not trusted: a course named `<script>alert(1)</script>` renders as
text. A `.tessera` project is a file that gets emailed between people, so "nobody would
type that" is not an argument available here.

## Templates travel as data

Jinja templates are read from disk at render time rather than imported, so they must be
listed in [`packaging/tessera-engine.spec`](../../packaging/tessera-engine.spec) as
`datas` and found under `sys._MEIPASS` once frozen — the same treatment Alembic's
migrations get, resolved through one module,
[`tessera/paths.py`](../../tessera/paths.py).

Miss it and the console works perfectly in development and serves a stack trace from the
`.dmg`. So `packaging/smoke-test.sh` runs the **bundled engine binary directly**, reads
its handshake for a token, and fetches a console page. Running it through the app instead
would give a `401` — which proves the route exists and nothing about whether the
templates travelled.

That check was verified the only way such a thing can be: by removing the templates from
the spec, rebuilding the `.dmg`, and watching it fail.

## Files

| | |
|---|---|
| [`api/console/base.py`](../../tessera/api/console/base.py) | the way in, the guards, `describe`, `SECTIONS` |
| [`api/console/places.py`](../../tessera/api/console/places.py) | the five declared sections |
| [`api/console/rooms.py`](../../tessera/api/console/rooms.py) | rooms — the shape the others copy |
| [`api/console/people.py`](../../tessera/api/console/people.py) | instructors and the availability grid |
| [`api/console/groups.py`](../../tessera/api/console/groups.py) | the student-group tree |
| [`api/console/calendar.py`](../../tessera/api/console/calendar.py) | teaching weeks and terms |
| [`api/console/teaching.py`](../../tessera/api/console/teaching.py) | courses, offerings, the weekly pattern, expand |
| [`api/console/solving.py`](../../tessera/api/console/solving.py) | pre-flight, generate, watch, stop, the infeasibility report |
| [`api/console/timetables.py`](../../tessera/api/console/timetables.py) | a term's candidates, and one read in three pivots |
| [`export/grid.py`](../../tessera/export/grid.py) | the projection all three renderers share |
| [`templates/solve/watch.js`](../../tessera/templates/solve/watch.js) | the console's only script — ADR-0017 |
| [`tessera/templates/`](../../tessera/templates) | one layout, one stylesheet, no framework |

## See also

- [API contract](api-contract.md) — the other presentation of the same repository
- [Teaching](teaching.md) — what the offering page is showing, and why expansion reconciles
- [Student groups](student-groups.md) — the relation the tree page renders
- [ADR-0017](../adr/0017-javascript-in-the-console.md) — why there is a script, and what a second one would have to answer
- [Solve jobs](solve-jobs.md) — the registry and the stream the solve pages drive
- [Solving](solving.md) — what the search is actually doing while the page counts
- [Packaging and the sidecar](packaging.md) — how the engine reaches a user at all
