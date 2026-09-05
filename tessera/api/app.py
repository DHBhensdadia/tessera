"""The FastAPI application.

A factory rather than a module-level instance so tests can build one against their own
project without touching global state, and so the engine can be started against whatever
file the user opened.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from sqlalchemy import Engine

import tessera
from tessera.api import console
from tessera.api.deps import ProjectState
from tessera.api.errors import ERROR_BASE, Problem, problem_response, register_error_handlers
from tessera.api.jobs import Registry
from tessera.api.logging import bind_request, configure_logging
from tessera.api.routers import (
    groups,
    health,
    imports,
    project,
    rules,
    solving,
    structure,
    teaching,
    timetables,
)
from tessera.repository.database import create_project_engine, session_factory

logger = structlog.get_logger(__name__)


def as_nullable_type(schema: Any, components: dict[str, Any] | None = None) -> Any:
    """Rewrite Pydantic's optional fields into the spelling OpenAPI 3.1 has for them.

    Pydantic renders `int | None` as `anyOf: [{type: integer}, {type: null}]`, which is
    valid and is not what 3.1 added `type: [integer, "null"]` for. Swift's generator maps
    the second and **silently drops** properties written the first way — every `*Update`
    model in this API came out as an empty struct, so nothing in the application could be
    edited and the client compiled perfectly while being unable to send a single PATCH.

    Applied to the document rather than to the models: it is a spelling difference in the
    same schema, the validation semantics are identical, and doing it here keeps the live
    document and the committed snapshot in agreement without annotating 91 fields.
    """
    if isinstance(schema, list):
        return [as_nullable_type(item, components) for item in schema]
    if not isinstance(schema, dict):
        return schema

    branches = schema.get("anyOf")
    # A nullable *reference* — `anyOf: [{$ref}, {type: null}]` — has no `type` to move into
    # an array, and the generator drops it exactly like the scalar case. Inlining the
    # referenced schema and marking it nullable is the spelling it maps.
    #
    # Inlining rather than `allOf: [{$ref}]`, which also generates: that wraps the value in
    # a synthetic single-member struct, so every call site reads `room.building?.value1.name`.
    # The duplication is a few lines in generated code nobody reads; the alternative is an
    # extra hop in code everybody reads.
    if isinstance(branches, list) and len(branches) == 2 and components is not None:
        refs = [b for b in branches if set(b) == {"$ref"}]
        nulls = [b for b in branches if b == {"type": "null"}]
        if len(refs) == 1 and len(nulls) == 1:
            name = refs[0]["$ref"].rsplit("/", 1)[-1]
            target = components.get(name)
            if isinstance(target, dict) and "type" in target:
                merged = {k: v for k, v in schema.items() if k != "anyOf"}
                merged.update({k: v for k, v in target.items() if k != "title"})
                merged["type"] = [target["type"], "null"]
                return as_nullable_type(merged, components)

    if isinstance(branches, list) and len(branches) == 2:
        nulls = [b for b in branches if b == {"type": "null"}]
        others = [b for b in branches if b != {"type": "null"}]
        if len(nulls) == 1 and len(others) == 1 and "type" in others[0]:
            merged = {k: v for k, v in schema.items() if k != "anyOf"}
            merged.update(as_nullable_type(others[0]))
            merged["type"] = [others[0]["type"], "null"]
            return merged

    return {key: as_nullable_type(value, components) for key, value in schema.items()}


def operation_id(route: APIRoute) -> str:
    """The name this endpoint carries in the OpenAPI document.

    FastAPI's default appends the path and the method, producing
    `list_rooms_api_v1_rooms_get` — which is unique, unreadable, and, worse, puts the URL
    inside the name. Anything generating a client from this document then hands every
    caller a method with the route baked into it, so moving a route renames a method at
    every call site. A typed client exists to insulate callers from the wire; a name like
    that does the opposite.

    The function name alone is enough here: all 109 operations have distinct names, which
    is checked by a test rather than hoped for. The path is what FastAPI adds to guarantee
    uniqueness, and dropping it is only safe while that holds.
    """
    head, *rest = route.name.split("_")
    return head + "".join(word.capitalize() for word in rest)


#: How the engine expects to be given its per-launch token.
#:
#: Declared so the published document says so. Authentication is enforced by middleware
#: rather than by a dependency, and FastAPI can only describe what it is told about — so
#: without this the contract advertises an API that needs no credentials and refuses every
#: request that arrives without one.
TOKEN_SCHEME = {
    "TesseraToken": {
        "type": "apiKey",
        "in": "header",
        "name": "x-tessera-token",
        "description": (
            "Issued once per engine launch and printed on stdout with the port. "
            "The console additionally accepts it as a cookie."
        ),
    }
}

DESCRIPTION = """
The Tessera engine: timetable data, constraint solving, and export.

One engine serves exactly one project, because a project *is* a file. There is
therefore no project identifier in any path.

Endpoints answering **501** are declared but not yet implemented. The contract is fixed
ahead of the handlers so that later work plugs into a known shape and clients can be
built against it; the response names the phase that implements each one.

Errors follow RFC 9457 Problem Details, on every route including framework failures.
""".strip()


#: Reachable without the token. The API surface is public knowledge — this is an open
#: source project — and the developer browsing it needs no credential. Everything that
#: touches the project's data does.
OPEN_PATHS = frozenset({"/docs", "/openapi.json", "/docs/oauth2-redirect"})

#: Names this engine will answer to. Anything else is a rebinding attempt: an attacker's own
#: domain pointed at loopback looks same-site to the browser, so `SameSite` alone would let
#: the request through.
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


async def refuse_foreign_host(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse anything that did not address this engine by a name it serves.

    **This used to check only `/console`, and 4.8 measured what that was worth.** With the
    session cookie set and `Host: evil.example`, `/console/rooms` answered 403 and
    `/api/v1/rooms` answered **200** — the same data on the same socket with one fewer
    defence, while Decision #65 recorded the console as *"the one place in Tessera where data
    becomes reachable from outside a private process boundary"*. It was not.

    It was also not a live hole, which is worth saying rather than dressing up: the console
    cookie is host-only, so a browser rebound to an attacker's domain sends that domain's
    cookie jar and the request arrives with no token at all. The token is what stops the
    attack on both paths. This is the second line, and it now exists on both.

    Costs a legitimate caller nothing — the Swift client and `curl` both send the loopback
    name they dialled. **A deployment binding beyond loopback has to widen `ALLOWED_HOSTS`**,
    which Stage 7's Docker image will have to do; `engine.main` already warns loudly when
    `--host` is not `127.0.0.1`, and this is the second thing that has to change with it.

    Middleware rather than a dependency so it covers routes added later, and so a mistake is
    a refusal rather than an omission.
    """
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        logger.warning("rejected_foreign_host", host=host, path=request.url.path)
        return Response("Not available on this host.", status_code=403)
    return await call_next(request)


def create_app(
    *,
    engine: Engine | None = None,
    project_path: Path | None = None,
    token: str | None = None,
    configure_logs: bool = True,
) -> FastAPI:
    """Build the application.

    ``token``, when given, is required on every request that is not in
    :data:`OPEN_PATHS`. The engine generates one per launch and announces it in its
    handshake, so only the process that read the handshake can reach the data — any
    other program on the machine can open the loopback port and gets nowhere. Passing
    ``None`` disables the check, which is what tests and local development want.
    """
    if configure_logs:
        configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = engine or (
            create_project_engine(project_path) if project_path is not None else None
        )
        if active is not None:
            app.state.project = ProjectState(
                engine=active,
                path=project_path,
                sessions=session_factory(active),
            )
            app.state.jobs = Registry(app.state.project)
            logger.info("engine_ready", project=app.state.project.name)
        yield
        # Only dispose what we opened. An engine handed in belongs to the caller, and
        # closing it here would break a test that reuses one across several apps.
        if engine is None and active is not None:
            active.dispose()

    app = FastAPI(
        title="Tessera",
        version=tessera.__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        generate_unique_id_function=operation_id,
    )

    def describe_authentication() -> dict[str, Any]:
        """Add the security scheme FastAPI cannot infer, once, and cache it.

        Enforcement lives in middleware, which the framework does not inspect, so the
        document has to be told. Applied globally rather than per route because the
        middleware is global — the two open paths are the interactive docs, which are not
        part of the API surface a client generates from.
        """
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.get("components", {}).get("schemas", {})
        schema = cast("dict[str, Any]", as_nullable_type(schema, components))
        schema.setdefault("components", {})["securitySchemes"] = TOKEN_SCHEME
        schema["security"] = [{"TesseraToken": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = describe_authentication  # type: ignore[method-assign]

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Give every request an id and put it on every log line it produces.

        A failure deep in the solver should still be traceable to the request that
        triggered it, and the id is echoed back so a user reporting a problem can quote
        something that appears in the log.
        """
        request_id = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
        bind_request(request_id, request.url.path, request.method)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    if token is not None:

        @app.middleware("http")
        async def require_token(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            if request.url.path in OPEN_PATHS:
                return await call_next(request)

            # Three carriers for one secret. A browser navigating to a URL can set
            # neither a header nor a cookie it does not yet have, so the console is
            # entered once through a link and presents a cookie from then on.
            #
            # The query string is accepted on **exactly one path** — the exchange itself.
            # Allowing it everywhere would put the token in history and logs on every
            # page; opening that path instead would mean a route that hands out cookies
            # without checking what it was given. Keeping it here leaves one place in the
            # application that decides whether a caller is authentic.
            supplied = (
                request.headers.get("x-tessera-token", "")
                or request.cookies.get(console.CONSOLE_COOKIE, "")
                or (
                    request.query_params.get("token", "")
                    if request.url.path == console.ENTRY_PATH
                    else ""
                )
            )
            # Constant-time: a plain == returns as soon as it finds a difference, so how
            # long it takes leaks how much of the token was right. Overkill for a
            # loopback socket, and the correct habit.
            if not secrets.compare_digest(supplied, token):
                logger.warning("rejected_unauthenticated", path=request.url.path)
                return problem_response(
                    Problem(
                        type=f"{ERROR_BASE}/unauthenticated",
                        title="Missing or invalid engine token",
                        status=401,
                        detail="Requests must carry the token from the engine handshake.",
                        instance=request.url.path,
                    )
                )
            return await call_next(request)

    register_error_handlers(app)

    app.middleware("http")(refuse_foreign_host)

    for module in (
        health,
        structure,
        groups,
        teaching,
        rules,
        imports,
        project,
        solving,
        timetables,
    ):
        app.include_router(module.router)
    app.include_router(console.router)

    return app
