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

    Renders JSON when stdout is not a terminal, which is exactly the case when the
    Swift client has spawned the engine and is capturing its output.
    """
    as_json = force_json or not sys.stdout.isatty()

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
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )

    # Uvicorn and SQLAlchemy log through the standard library. Without this their
    # output would be interleaved in a different format, which defeats the point of
    # structured logs the moment anything goes wrong at startup.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())


def bind_request(request_id: str, path: str, method: str) -> None:
    """Attach request identity to every log line emitted while handling it.

    Context variables rather than passing a logger around: a failure deep in the solver
    should still be traceable to the request that triggered it.
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=path, method=method)
