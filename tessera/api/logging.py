"""Structured logging.

The engine runs as a subprocess with no terminal of its own, so its log is read either
by a developer tailing it or by the client surfacing it after a crash. Neither is served
well by free-form strings: the first wants readability, the second wants fields it can
parse.

structlog handles both from one call site — human-readable when attached to a terminal,
JSON when not.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, level: str = "INFO", force_json: bool = False) -> None:
    """Set up logging for the process. Call once, at startup.

    **Everything is written to stderr.** stdout carries exactly one thing — the engine's
    startup handshake — and anything else printed there corrupts it. Alembic in
    particular logs during migration, which happens moments before the handshake is
    emitted; with logging on stdout the client reads a log line where it expects JSON
    and concludes the engine is broken.

    Renders JSON when stderr is not a terminal, which is the case whenever the desktop
    application has spawned the engine and is capturing its output.
    """
    as_json = force_json or not sys.stderr.isatty()

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            (
                structlog.processors.JSONRenderer()
                if as_json
                else structlog.dev.ConsoleRenderer(colors=True)
            ),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )

    # Uvicorn, SQLAlchemy and Alembic log through the standard library. Routed to
    # stderr alongside our own, both so the format is consistent and so none of them can
    # write to the stdout channel the handshake owns.
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level.upper(), force=True)


def bind_request(request_id: str, path: str, method: str) -> None:
    """Attach request identity to every log line emitted while handling it.

    Context variables rather than passing a logger around: a failure deep in the solver
    should still be traceable to the request that triggered it.
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=path, method=method)
