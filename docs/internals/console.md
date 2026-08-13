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
| [`tessera/templates/`](../../tessera/templates) | one layout, one stylesheet, no framework |

## See also

- [API contract](api-contract.md) — the other presentation of the same repository
- [Teaching](teaching.md) — what the offering page is showing, and why expansion reconciles
- [Student groups](student-groups.md) — the relation the tree page renders
- [Packaging and the sidecar](packaging.md) — how the engine reaches a user at all
