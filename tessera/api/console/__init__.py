"""The browser console.

See `base` for how a browser gets past the engine token, and what stops the cookie it
receives being usable by any other page.

Importing a section module is what registers its routes on the shared router, so each
one is named in ``__all__`` rather than imported for its side effect and suppressed —
there is no ``noqa`` in this codebase.
"""

from __future__ import annotations

from tessera.api.console import rooms
from tessera.api.console.base import (
    CONSOLE_COOKIE,
    ENTRY_PATH,
    describe,
    guard_console,
    page,
    redirect,
    router,
)

__all__ = [
    "CONSOLE_COOKIE",
    "ENTRY_PATH",
    "describe",
    "guard_console",
    "page",
    "redirect",
    "rooms",
    "router",
]
