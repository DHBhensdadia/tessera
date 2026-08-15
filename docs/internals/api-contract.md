# The API contract

56 paths, 89 operations, published before most of the handlers exist. The point of
freezing it early is that everything built afterwards plugs into a known shape: the
client can be written against a mock, the solver can be replaced without the interface
noticing, and two pieces of work cannot drift apart because both target the same
contract.

Browse it live at `/docs`, or read `docs/openapi.json`.

## Shape

```
/health                        liveness — what the client polls after spawning the engine
/api/v1/meta                   version and schema revision
/api/v1/…                      everything else
```

**There is no project identifier anywhere.** A Tessera project *is* a file, and one
engine serves exactly one of them, so the project is process state rather than a path
segment. If server mode ever needs several, the answer is one container per project, not
a redundant segment on every URL for the rest of the project's life.

`/api/v1` exists as the hedge against that judgement being wrong, and because the Docker
image and the CLI are consumed independently of the client in a way the sidecar is not.

## Unimplemented routes answer 501

A declared-but-unimplemented route returns **501 Not Implemented**, naming the phase
that will implement it:

```json
{
  "type":   "https://tessera.dev/errors/not-implemented",
  "title":  "Not implemented yet",
  "status": 501,
  "detail": "This endpoint is implemented in phase 2.1."
}
```

404 would say the endpoint does not exist. The entire point is that it does, and that
its shape is already agreed.

## Errors are RFC 9457, everywhere

One envelope for every failure, including the ones raised by FastAPI rather than by us —
a client forced to decode two different error shapes will eventually mishandle one.

```json
{
  "type":     "https://tessera.dev/errors/validation-failed",
  "title":    "Validation failed",
  "status":   422,
  "detail":   "2 field(s) failed validation",
  "instance": "/api/v1/timetables/1/validate-viewport",
  "errors":   [{"pointer": "body/room_ids", "message": "List should have at least 1 item"}]
}
```

`errors` is an RFC 9457 extension member. It exists because the errors this application
actually raises are plural and located: a spreadsheet fails on row 14 *and* row 88 for
different reasons, and an infeasible term fails because three specific constraints
cannot coexist. FastAPI's default `{"detail": "some string"}` cannot express either.

Unexpected exceptions return a generic message; the detail goes to the log, since an
unhandled exception can carry file paths or query fragments.

## Validation is always viewport-scoped 🔒

Two routes, and deliberately no third:

```
POST /api/v1/timetables/{id}/validate-move        one cell
POST /api/v1/timetables/{id}/validate-viewport    every visible cell, one call
```

**There is no whole-grid variant, and `test_no_unscoped_validation_endpoint_exists`
exists to stop one being added.** Phase 0.2 measured an unscoped check at **43 ms p99**
at the NFR-9 ceiling against a 16 ms frame budget, while viewport-scoped ran at 7.4 ms
over the same data. An unscoped endpoint would pass every test at department scale and
fail only for the largest institutions, only in production.

`validate-viewport` is called **once** when a drag begins; the interface renders green
and red from the result and makes no further calls while the pointer moves. Roughly 600×
less transport than checking each cell as the cursor crosses it.

Both are `POST` despite being reads: a viewport can name 500 rooms, which does not fit
comfortably in a query string, and the two are kept consistent so the client has one
calling convention rather than two.

## Sync handlers, with async where it earns it

CRUD handlers are plain `def`. Sync SQLAlchemy inside `async def` blocks the event loop;
FastAPI runs sync handlers in a threadpool, which is both correct and simpler.

`async def` is used only where it buys something — the SSE solve stream, and file
uploads. Async SQLAlchemy remains available if server mode ever needs it.

## Wire models are not domain models

`tessera/api/schemas/` is a separate set of Pydantic models from `tessera/domain/`.

The duplication is deliberate and is the same trade Decision #14 made when choosing
SQLAlchemy over SQLModel: the published contract is a stability guarantee and must be
free to differ from the in-memory shape, to omit fields, and to change on a different
schedule from the database. Collapsing them would mean a storage change could silently
become a breaking API change.

Wire models also carry things the domain has no reason to know about — `Reference`
embeds a name alongside an id so the client can render a grid without a second request
per related object.

## The snapshot guard

`docs/openapi.json` is committed, and `tests/api/test_contract.py` compares it against
the live application.

It compares **shape, not bytes**: byte-equality would fail on every FastAPI upgrade, so
Dependabot would turn the guard into noise — and a guard that cries wolf gets silenced,
which is worse than not having one.

What it compares has been wrong twice, in the same way both times — it covered less than
it appeared to, and nobody knew because it had never been watched fail:

| Added | Covers | Found by |
|---|---|---|
| 1.4 | (method, path) pairs and operation ids — the latter become method names in a generated client, so renaming one breaks it even when the URL does not change | — |
| 2.2 (#46) | query and path **parameters**. Dropping a required one is unambiguously breaking and passed silently | removing a parameter and watching the suite stay green |
| 2.8 | schema **fields**, and fields that become newly required. The model test compared schema *names*, so deleting a field from a response model passed | deleting `ConstraintRead.target_ids` after regenerating the snapshot, exactly as Decision #43 requires, and watching nothing happen |

**Only removals fail.** Adding a parameter or a field is additive and safe, which is how
2.2's selective unavailability delete and 2.8's `targets` both arrived without breaking
the frozen surface. A field going from optional to required fails too: it breaks a caller
written against the old shape just as surely as deleting one.

The lesson is not about OpenAPI. A guard that has never been seen to fail is not known to
work, and "we have a contract test" is the sentence that stops anyone checking.

When a contract change is intentional:

```bash
uv run tessera-openapi
```

An explicit step, so a contract change is always a deliberate commit rather than a side
effect of editing a router.

## Request identity

Every request gets an `x-request-id`, bound to the structlog context so it appears on
every line that request produces, and echoed back in the response header. A failure deep
in the solver stays traceable to the request that caused it, and a user reporting a
problem can quote something that actually appears in the log.
