"""The browser console: a plain HTML UI over the same repository the API uses.

It exists so the backend is usable and testable by hand months before any Swift, which
takes the native client off the critical path entirely. Deliberately plain — a tool, not
a design exercise — and server-rendered, so it works with JavaScript disabled and stays
legible as a tool rather than growing into a second product.

Handlers call `tessera.repository` directly, exactly as the API routers do. They are two
presentations of one set of rules, not two implementations: nothing here decides
anything. What is *not* shared is failure rendering, because a 409 has to arrive as a
sentence beside a field rather than as a JSON envelope.

## Getting in

The engine protects every route with a token announced in its handshake, so that any
other program on the machine can open the loopback port and get nowhere. **A browser
navigating to a URL cannot set a header**, so the console trades the token for a cookie:

    GET /console?token=<from the handshake>   ->  sets the cookie, redirects to /console

The token is in a URL once, which is one entry in history rather than one per page. The
redirect is immediate and the response carries `Referrer-Policy: no-referrer` so it does
not leak onward. This is what Jupyter does, for the same reason.

## Why a cookie needs two extra defences

A cookie is presented by the browser automatically, which is the point — and the risk.
Any page the user is visiting could submit a form to `http://127.0.0.1:<port>/console/…`
and the browser would attach the session.

* **`SameSite=Strict`** means it is not attached to cross-site requests at all.
* **A `Host` check** closes the gap `SameSite` cannot see: with DNS rebinding an
  attacker's own domain resolves to loopback, so the request genuinely *is* same-site.
  Only `localhost` and `127.0.0.1` are served.

Neither costs anything. This is the one place in Tessera where data becomes reachable
from outside a private process boundary, and it is worth being deliberate rather than
lucky about it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from tessera import paths
from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError

router = APIRouter(prefix="/console", tags=["console"])

#: The session cookie. Defined here rather than in `app` because the app imports this
#: package for its router — the dependency runs one way only.
CONSOLE_COOKIE = "tessera_session"

#: The one path on which the token may arrive as a query parameter. Its entire job is to
#: trade that for a cookie; every other path takes the header or the cookie.
ENTRY_PATH = "/console"

templates = Jinja2Templates(directory=str(paths.templates_directory()))

#: Hosts the console will answer on. Anything else is a rebinding attempt: an attacker's
#: domain pointed at loopback looks same-site to the browser, so `SameSite` alone would
#: let the request through.
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def _host_is_local(request: Request) -> bool:
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    return host in ALLOWED_HOSTS


@dataclass(frozen=True)
class Section:
    """One entry in the navigation, and one row on the overview.

    A list rather than markup because there will be a dozen of these before the phase is
    out, and hand-editing two places per section is how one of them ends up missing from
    the menu and reachable only by typing the URL.
    """

    slug: str
    label: str
    blurb: str

    @property
    def href(self) -> str:
        return f"/console/{self.slug}"


SECTIONS: tuple[Section, ...] = (
    Section("institutions", "Institutions", "The university, and anything sharing this file"),
    Section("departments", "Departments", "Who owns courses, programmes and staff"),
    Section("buildings", "Buildings", "Where rooms are"),
    Section("rooms", "Rooms", "Where teaching happens: capacity and equipment"),
    Section("features", "Equipment", "What a room can offer, and what a session can need"),
    Section("instructors", "Instructors", "Teaching staff, and when they cannot teach"),
    Section("programs", "Programmes", "Degrees, and the intakes beneath them"),
    Section("student-groups", "Student groups", "Intakes, lab batches and electives"),
)


def page(request: Request, template: str, **context: Any) -> HTMLResponse:
    """Render a template with the things every page needs.

    `sections` is injected here rather than passed by each handler, so a new section
    appears in the navigation by existing rather than by being remembered.
    """
    context.setdefault("sections", SECTIONS)
    context.setdefault("here", request.url.path)
    return templates.TemplateResponse(request=request, name=template, context=context)


def redirect(to: str) -> RedirectResponse:
    """Post-redirect-get, so a refresh never resubmits a form."""
    return RedirectResponse(url=to, status_code=status.HTTP_303_SEE_OTHER)


def describe(error: Exception) -> str:
    """A repository failure as a sentence someone can act on.

    The API turns these into RFC 9457 documents; a form needs prose. Same errors, same
    meanings, different medium — which is the one thing the console does not share with
    the routers.
    """
    if isinstance(error, ConflictError):
        blockers = ", ".join(
            f"{count} {kind.replace('_', ' ')}" for kind, count in error.blockers.items()
        )
        return f"{error.message}{f' ({blockers})' if blockers else ''}"
    if isinstance(error, InvalidReferenceError):
        return f"{error.field} refers to something that does not exist: {error.missing}"
    if isinstance(error, NotFoundError):
        return "That record no longer exists."
    return str(error)


async def guard_console(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse console requests that did not come from a browser on this machine.

    Registered as middleware rather than a dependency so it covers every console route
    including ones added later, and so a mistake is a refusal rather than an omission.
    """
    if request.url.path.startswith("/console") and not _host_is_local(request):
        return Response("Not available on this host.", status_code=status.HTTP_403_FORBIDDEN)
    return await call_next(request)


@router.get("", include_in_schema=False)
def enter(request: Request, token: str | None = None) -> Response:
    """Trade the handshake token for a session cookie, then redirect to a clean URL.

    Arriving with no token and no cookie is not an error — the token check in
    `create_app` has already rejected that request. Reaching this handler at all means
    the caller is authenticated, by one carrier or the other.
    """
    if token is None:
        return page(request, "index.html")

    response = redirect("/console/")
    response.set_cookie(
        CONSOLE_COOKIE,
        token,
        httponly=True,  # unreachable from any script on the page
        samesite="strict",  # never attached to a cross-site request
        secure=False,  # loopback is plain http; Secure would stop it being sent at all
        path="/",
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/", include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    return page(request, "index.html")
