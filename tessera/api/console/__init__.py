"""The browser console.

See `base` for how a browser gets past the engine token, and what stops the cookie it
receives being usable by any other page.

Importing a section module is what registers its routes on the shared router, so each
one is named in ``__all__`` rather than imported for its side effect and suppressed —
there is no ``noqa`` in this codebase.

**Order matters.** `places` ends with a catch-all `/{slug}` route, so every section with
a path of its own has to be imported before it or the catch-all swallows the path first.
"""

from __future__ import annotations

from tessera.api.console import calendar, groups, people, places, rooms, teaching
from tessera.api.console.base import (
    CONSOLE_COOKIE,
    ENTRY_PATH,
    SECTIONS,
    Section,
    describe,
    guard_console,
    page,
    redirect,
    router,
)

__all__ = [
    "CONSOLE_COOKIE",
    "ENTRY_PATH",
    "SECTIONS",
    "Section",
    "calendar",
    "describe",
    "groups",
    "guard_console",
    "page",
    "people",
    "places",
    "redirect",
    "rooms",
    "router",
    "teaching",
]
