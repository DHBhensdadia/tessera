"""The FastAPI application.

A factory rather than a module-level instance so tests can build one against their own
project without touching global state, and so the engine can be started against whatever
file the user opened.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from sqlalchemy import Engine

import tessera
from tessera.api.deps import ProjectState
from tessera.api.errors import register_error_handlers
from tessera.api.logging import bind_request, configure_logging
from tessera.api.routers import (
    groups,
    health,
    imports,
    rules,
    solving,
    structure,
    teaching,
    timetables,
)
from tessera.repository.database import create_project_engine, session_factory

logger = structlog.get_logger(__name__)

DESCRIPTION = """
The Tessera engine: timetable data, constraint solving, and export.

One engine serves exactly one project, because a project *is* a file. There is
therefore no project identifier in any path.

Endpoints answering **501** are declared but not yet implemented. The contract is fixed
ahead of the handlers so that later work plugs into a known shape and clients can be
built against it; the response names the phase that implements each one.

Errors follow RFC 9457 Problem Details, on every route including framework failures.
""".strip()


def create_app(
    *,
    engine: Engine | None = None,
    project_path: Path | None = None,
    configure_logs: bool = True,
) -> FastAPI:
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
    )

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

    register_error_handlers(app)

    for module in (health, structure, groups, teaching, rules, imports, solving, timetables):
        app.include_router(module.router)

    return app
