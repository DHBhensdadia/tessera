# ADR-0017: The console gets one hand-written script, and a written boundary around it

**Status:** Accepted · **Date:** 2026-09-05

## Context

The browser console was built in Phase 2.5 as *"deliberately plain — a tool, not a design
exercise"*, and that plan's D6 chose server-rendered forms and post-redirect-get with one
sentence of latitude:

> A small amount of hand-written JS is allowed where a form would otherwise be unusable — the
> availability grid is the likely case. No framework, no build step.

The availability grid turned out not to need any. Three years of console pages later, the
repository contains **no `<script>` element at all** — sixteen templates, one inline
`onchange` on a term selector, and a `<noscript>` button beside it.

Phase 4.8 puts a solve behind a button, and *watch live progress* is the second case that
clause anticipated. It is larger than the first, so the latitude is spent deliberately here
rather than stretched quietly.

**What the alternative costs was measured rather than assumed.** A page that refreshes itself
is the only script-free way to show a solve moving:

| | over a five-minute solve |
|---|---|
| SSE at the stream's own 250 ms cadence | **357 KiB**, one connection, page never discarded |
| meta refresh every 1 s | ~1.5 MB, **300 requests**, 300 renders, 300 database reads |
| meta refresh every 2 s | ~750 KB, 150 requests, and a clock that visibly stutters |

The stream is smaller *and* better, which is not the usual shape of this trade-off. It also
makes one clause of the phase's exit test observable at all: *the penalty never rises* cannot
be seen across independent full-page renders, and on a term where the solver reports one
improvement in thirty seconds a static number is indistinguishable from a hung page.

## Decision

**One hand-written script, `tessera/templates/solve/watch.js`, on one page, under four rules.**

1. **Progressive enhancement, not a requirement.** The page is fully server-rendered and
   complete without the script. A browser with scripting off gets the same markup and a
   `<noscript>` meta refresh; it loses the curve and nothing else. The exit test verifies the
   whole generate-and-view cycle with scripting disabled, in a browser, rather than by
   asserting a `<noscript>` element is present.

2. **No framework, no build step, no CDN.** NFR-1 is absolute — zero network dependency — so
   a script that fetched anything at run time would break the product's first requirement.
   `EventSource` is a browser built-in and the chart is an inline `<polyline>`. htmx was
   considered and rejected: it would put a third-party minified blob into a repository that is
   a work product, to buy what sixty lines already do.

3. **It lives in `templates/` and is `{% include %}`d.** Still one HTTP response, and still
   nothing new for PyInstaller to carry — `templates/` is already bundled, which is the whole
   of Decision #66. A `static/` directory would need a path resolver, a `sys._MEIPASS` branch,
   a `datas` entry, a mount and a smoke-test check, for one file.

4. **The script contains no template expression, and a test says so.** Starlette builds its
   Jinja environment with `select_autoescape()`, which escapes `.html` and **does not escape
   `.js`**. Measured: the same value through a page and through an included script comes out
   escaped on one side and raw on the other, in one response. So everything the script needs
   arrives on `data-` attributes of the element it upgrades, which are autoescaped because
   they live in the HTML.

**The server keeps the prose.** When a solve settles the script closes the stream and reloads,
so which ending it was — and whether the budget or the arithmetic stopped it — is written in
one place, `console.solving.wording`, rather than copied into JavaScript that would drift
from it.

**The stream is the API's, not the console's.** `GET /api/v1/solve/{id}/stream` is published in
the contract and is what the native panel will use; the console is its first client rather than
a rehearsal of it. Only the *actions* are console routes, because a form cannot post to
something that answers 202 with a JSON body.

## The boundary

This is the D6 permission used for its second case, and it is the last one it covers. **A third
scripted page is a new decision, not a precedent**, and it should arrive with an answer to two
questions this one did not have to answer:

- **How is it tested?** Nothing in this project runs JavaScript. What guards `watch.js` is a
  contract test that reads the ids and `data-` attributes out of the script and asserts the
  template renders them, plus running it in a real browser and writing down what was seen. That
  is proportionate to sixty lines on one page. It does not scale to a second one, and the
  trigger for adopting a headless browser is written into the backlog rather than left to
  whoever hits it.
- **Is the page still complete without it?** Rule 1 is what keeps the console a tool rather
  than a second product competing with the native application, which is what 2.5's D6 was
  protecting. A page that *requires* a script has left that behind and needs its own argument.

## Consequences

- The console has a live progress page with a descending curve, and 5.3 inherits a wire format
  that has been exercised by a real client rather than only by `curl`.
- The curve starts when the page connected, not when the solve did. `SolveStatus` carries no
  trajectory and widening it was refused in 4.7 (#306); the caption says so rather than
  implying a history the client does not have.
- Two behaviours of `EventSource` had to be written against on purpose: it reconnects for ever
  three seconds after the server closes a stream, and an open stream holds one of the six
  connections a browser will make to an origin over HTTP/1.1. Both are closed — on `done` and
  on `pagehide`.
- A CSP would now be worth having, and there is none. Backlogged with the escaping measurement
  attached, so the next person meets the reasoning rather than the conclusion.

## Alternatives rejected

| | why not |
|---|---|
| No script at all, meta refresh only | Measured above: larger, worse, and it makes one exit-test clause unobservable |
| Inline `<script>` in the template | Autoescaped, so safe — but the code is then trapped in HTML where no editor, formatter or grep treats it as code |
| A `static/` directory | Decision #66 again, in full, for one file and one extra request per page |
| htmx, vendored | Contradicts 2.5's *no framework*; a third-party blob in a work product; buys nothing the sixty lines do not |
| Requiring JavaScript and dropping the server-rendered half | Halves the code and ends the console's reason for existing — a tool that works with anything, months before the native client |
