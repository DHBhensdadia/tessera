# The API client

How Swift talks to the engine, and why almost none of it is written by hand.

## Generated, not written

`client/Sources/EngineClient` contains four small files and no operations. The 109
operations and 114 models are generated at build time by
[swift-openapi-generator](https://github.com/apple/swift-openapi-generator) from the
committed OpenAPI document — **71,494 lines**, none of it in the repository.

The reason is not the typing effort. A hand-written client can fall behind the contract
without anything saying so, and 109 operations is enough surface for that to be a certainty
rather than a risk. Generated, drift is a **compile error**: an endpoint that disappears from
the engine disappears from the type, and the code that called it stops building.

The cost is a cold build that went from 9 s to 115 s. Accepted deliberately (#134):
incremental builds are unaffected, and the alternative — committing the generated lines —
puts the largest file nobody wrote into a repository whose premise is that it reads as
somebody's work.

## The chain that keeps four things in agreement

The document exists twice, because SwiftPM plugins are sandboxed to their package directory
and cannot read `docs/`. Two copies of a contract is a drift risk, so every link is guarded
rather than trusted:

| link | held by |
|---|---|
| engine ↔ `docs/openapi.json` | the Python contract suite — operations, parameters, schema names, fields, response models, and now the version |
| `docs/openapi.json` ↔ `client/Sources/EngineClient/openapi.json` | `scripts/check.sh` — byte comparison, and `tessera-openapi` writes both in one function |
| document ↔ generated client | the build plugin, every build |
| generated client ↔ call sites | the compiler |

`ReachabilityTests` sits across the third link and is honest about what it can see: it cannot
fail by adding an operation to the document, because the plugin regenerates from that same
document. What it catches is a generator **config** that drops operations — for the hundred
or so nothing calls yet. For the handful that are called, dropping them fails to compile.

## Names, and why 109 Python routes changed

FastAPI derives operation ids from the function name *plus the path plus the method*:
`list_rooms_api_v1_rooms_get`, 47 characters on average. A generated client names its methods
after those, so every screen would carry the URL inside a method name and moving a route
would rename a method at twenty call sites — the opposite of what a typed client is for.

One `generate_unique_id_function` fixes it centrally (#131). Safe only because all 109
endpoint function names are distinct, which a test asserts rather than assumes.

## Three middlewares, and their order is the reasoning

```
RetryMiddleware  →  ProblemMiddleware  →  TokenMiddleware  →  the wire
```

**Retry is outermost** so it sees a transport failure before anything has interpreted it.
It repeats GET, PUT and DELETE — never POST, because a create that timed out after the write
is indistinguishable from one that never arrived, and asking again produces two rooms. Two
retries, backing off from 100 ms: loopback either answers or is gone.

**Problem mapping sits inside it**, turning every 4xx and 5xx into an `EngineFailure` once,
for all 109 operations. Without it each call site would switch over an enum that exists for
one endpoint. It also means retry can tell a refusal from a hiccup: a 409 is a decision, and
asking again gets the same answer.

**The token goes on last**, so every attempt including retries carries it. One place rather
than 109 opportunities to forget.

## A failure keeps its shape

The engine answers RFC 9457, and `EngineFailure` keeps that structure to the view. The
distinction that matters for the forms in 3.4: a **422 is a field error** and belongs beside
an input, a **409 is a rule violation** with a sentence the engine already wrote.

```
refused   409 ConflictError — a building called 'Block A' already exists here
refused   422 — 1 field(s) failed validation
          field 'name' (body/name): String should have at least 1 character
```

Field complaints arrive as JSON Pointers — `body/name`, `rows/14/capacity` — and
`fieldName` takes the last non-numeric component, because a complaint about
`rows/14/capacity` is about capacity, not about 14.

**A middleware that throws does not throw to the caller.** `Client` catches it and rethrows a
`ClientError` carrying the original as `underlyingError`, so `catch let failure as
EngineFailure` never matches. `EngineConnection.run` unwraps it, which is why every call site
uses it. That was found by running the probe, not by reading the code — the middleware had
been producing exactly the right value all along.

## `--probe`

`Tessera --probe` starts an engine on a throwaway project and exercises the happy path, a
409, a 422, a 404 and a dead engine, printing what came back. It exists because a generated
client compiles against a document rather than a server: in this phase alone, `swift build`
was green while the plugin generated nothing, while the base URL doubled the path prefix,
and while no call site could catch the typed failure.

## What is not here

**Pagination.** The engine has none — `Page` carries `items` and `total`, and no route
accepts `limit` or `offset`. The hand-written client 3.3 replaced sent `?limit=1` and
carried a comment claiming this avoided downloading every row; FastAPI ignored the unknown
parameter and the claim was never true. The generated client cannot send it at all, which is
how the falsehood surfaced. Counting a collection downloads it. Fine at a department's
scale, not at P1's ceiling — in the backlog as an engine change.

**Engine restart under a live window.** Re-launching means a new port, a new token and every
open request re-issued. A phase, not a paragraph; backlogged.

**Streaming.** `ProblemMiddleware` reads response bodies whole. Correct for Problem Details
and wrong for a stream, which the engine does not have until Stage 5 sends solver progress.
That needs revisiting rather than extending.

## See also

- [The app shell](shell.md) — who owns a connection, and for how long
- [Packaging and the sidecar](packaging.md) — how the engine gets to the client
