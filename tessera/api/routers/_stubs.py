"""Helpers for routes whose contract is frozen before their implementation exists.

Phase 1.4 publishes the whole surface so that later phases plug into a known shape and
the client can be built against a mock. A route that is declared but unimplemented
answers 501 — not 404, which would say it does not exist when the entire point is that
it does.
"""

from __future__ import annotations

from typing import NoReturn

from tessera.api.errors import NotImplementedYetError


def pending(phase: str, what: str = "") -> NoReturn:
    """Raise the 501 for a route implemented in a later phase."""
    raise NotImplementedYetError(phase, what)
