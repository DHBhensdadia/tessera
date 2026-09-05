"""The browser console.

See `base` for how a browser gets past the engine token, and what stops the cookie it
receives being usable by any other page.

Importing a section module is what registers its routes on the shared router, so each
one is named in ``__all__`` rather than imported for its side effect and suppressed —
there is no ``noqa`` in this codebase.

Import order used to matter, because `places` ended with a catch-all `/{slug}` and
whichever module registered first won the path — so sorting the imports alphabetically
silently broke `/console/rooms`. It binds an explicit route per slug now (Decision #67),
and the ordering hazard is gone with it.
"""

from __future__ import annotations

from tessera.api.console import (
    calendar,
    groups,
    imports,
    people,
    places,
    rooms,
    rules,
    teaching,
)
from tessera.api.console.base import (
    CONSOLE_COOKIE,
    ENTRY_PATH,
    SECTIONS,
    Section,
    describe,
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
    "imports",
    "page",
    "people",
    "places",
    "redirect",
    "rooms",
    "router",
    "rules",
    "teaching",
]
