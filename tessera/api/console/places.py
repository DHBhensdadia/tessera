"""Institutions, departments, buildings, equipment and programmes.

These five are the same form five times: a name, sometimes a code, sometimes a parent to
sit under. Writing them out separately would be three hundred lines differing in a noun,
and the copies would drift — the missing `exclude_id` that 2.4b had to fix once would
have been five separate omissions waiting to happen.

So they are declared rather than written. Instructors and student groups are **not** here,
because they are genuinely different: one owns a week of availability, the other a tree.
The moment an entity needs more than a name, a code and a parent it gets its own module,
and this table does not grow a special case.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from inspect import signature
from typing import Any

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.repository import groups as groups_repo
from tessera.repository import structure as repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class Kind:
    """One declared section.

    The callables are passed rather than looked up by name so that a typo is an import
    error at start-up rather than a 500 on the one page nobody opened.
    """

    slug: str
    title: str
    lede: str
    list_all: Callable[..., Sequence[Any]]
    create: Callable[..., Any]
    update: Callable[..., Any]
    delete: Callable[..., Any] | None
    has_code: bool = False
    parent_field: str | None = None  # the create kwarg, e.g. "institution_id"
    parent_label: str = ""
    parent_options: Callable[[Db], Sequence[Any]] | None = None
    parent_required: bool = True


KINDS: tuple[Kind, ...] = (
    Kind(
        slug="institutions",
        title="Institutions",
        lede="Usually one. A project file can hold more, and nothing is shared between them.",
        list_all=repo.list_institutions,
        create=repo.create_institution,
        update=repo.update_institution,
        delete=repo.delete_institution,
    ),
    Kind(
        slug="departments",
        title="Departments",
        lede="Who owns courses, programmes and staff.",
        list_all=repo.list_departments,
        create=repo.create_department,
        update=repo.update_department,
        delete=repo.delete_department,
        has_code=True,
        parent_field="institution_id",
        parent_label="Institution",
        parent_options=repo.list_institutions,
    ),
    Kind(
        slug="buildings",
        title="Buildings",
        lede="Where rooms are. Room numbers repeat between buildings constantly.",
        list_all=repo.list_buildings,
        create=repo.create_building,
        update=repo.update_building,
        delete=repo.delete_building,
        parent_field="institution_id",
        parent_label="Institution",
        parent_options=repo.list_institutions,
    ),
    Kind(
        slug="features",
        title="Equipment",
        lede="What a room can offer, and what a session can require of one.",
        list_all=repo.list_features,
        create=repo.create_feature,
        update=repo.update_feature,
        delete=repo.delete_feature,
        parent_field="institution_id",
        parent_label="Institution",
        parent_options=repo.list_institutions,
    ),
    Kind(
        slug="programs",
        title="Programmes",
        lede="Degrees. Intakes hang beneath these as student groups.",
        list_all=groups_repo.list_programs,
        create=groups_repo.create_program,
        update=groups_repo.update_program,
        delete=groups_repo.delete_program,
        has_code=True,
        parent_field="department_id",
        parent_label="Department",
        parent_options=repo.list_departments,
        parent_required=False,
    ),
)

BY_SLUG = {kind.slug: kind for kind in KINDS}


def _bind(handler: Callable[..., Response], slug: str) -> Callable[..., Response]:
    """The same handler, with its `slug` already answered.

    `functools.partial` will not do: FastAPI reads the signature to work out what to
    inject, and a partial hides it. Rewriting the signature without the bound parameter
    is what lets the remaining ones — the form fields, the database — still be seen.
    """

    def bound(*args: Any, **kwargs: Any) -> Response:
        return handler(slug, *args, **kwargs)

    original = signature(handler)
    bound.__signature__ = original.replace(  # type: ignore[attr-defined]
        parameters=[p for name, p in original.parameters.items() if name != "slug"]
    )
    bound.__name__ = f"{handler.__name__}_{slug}"
    return bound


def _render(
    request: Request, db: Db, kind: Kind, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    parents = list(kind.parent_options(db)) if kind.parent_options else []
    return page(
        request,
        "places/list.html",
        kind=kind,
        rows=list(kind.list_all(db)),
        parents=parents,
        problem=problem,
        **extra,
    )


def _kind_or_404(slug: str) -> Kind:
    kind = BY_SLUG.get(slug)
    if kind is None:  # pragma: no cover - unreachable: FastAPI matches the literal paths
        raise KeyError(slug)
    return kind


def list_kind(slug: str, request: Request, db: Db) -> Response:
    return _render(request, db, _kind_or_404(slug))


def create_one(
    slug: str,
    request: Request,
    db: Db,
    name: str = Form(...),
    code: str = Form(""),
    parent_id: str = Form(""),
) -> Response:
    kind = _kind_or_404(slug)
    fields: dict[str, Any] = {"name": name}
    if kind.has_code:
        fields["code"] = code
    if kind.parent_field:
        fields[kind.parent_field] = int(parent_id) if parent_id else None

    try:
        kind.create(db, **fields)
    except RepositoryError as error:
        return _render(
            request, db, kind, problem=describe(error), submitted={"name": name, "code": code}
        )
    except TypeError:
        # A required parent arrived empty. The repository's signature says it is not
        # optional, so this is the form failing to collect it rather than a rule.
        return _render(
            request,
            db,
            kind,
            problem=f"{kind.parent_label} is required.",
            submitted={"name": name, "code": code},
        )
    return redirect(f"/console/{slug}")


def rename_one(
    slug: str,
    identifier: int,
    request: Request,
    db: Db,
    name: str = Form(...),
    code: str = Form(""),
) -> Response:
    """Renaming exists because until 2.4b it did not, and a mistyped name was permanent."""
    kind = _kind_or_404(slug)
    changes: dict[str, Any] = {"name": name}
    if kind.has_code:
        changes["code"] = code
    try:
        kind.update(db, identifier, changes=changes)
    except RepositoryError as error:
        return _render(request, db, kind, problem=describe(error))
    return redirect(f"/console/{slug}")


def delete_one(slug: str, identifier: int, request: Request, db: Db) -> Response:
    kind = _kind_or_404(slug)
    if kind.delete is None:  # pragma: no cover - every kind here has one
        return _render(request, db, kind, problem="These cannot be deleted.")
    try:
        kind.delete(db, identifier)
    except RepositoryError as error:
        return _render(request, db, kind, problem=describe(error))
    return redirect(f"/console/{slug}")


# --------------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------------
#
# Each kind gets its own explicit paths rather than one `/{slug}` catch-all.
#
# A catch-all would have to be registered *after* every bespoke section — instructors,
# student groups — or it would swallow their paths first. That makes route matching
# depend on import order, which a formatter is free to rearrange: sorting this module's
# import alphabetically was enough to break it, silently, with every test still passing
# except the one that fetched `/console/rooms`.
#
# Explicit paths cannot be reordered into a bug, and an unknown slug is a plain 404
# rather than a page pretending to be a section.
for _kind in KINDS:
    router.add_api_route(
        f"/{_kind.slug}",
        _bind(list_kind, _kind.slug),
        methods=["GET"],
        include_in_schema=False,
        name=f"console_list_{_kind.slug}",
    )
    router.add_api_route(
        f"/{_kind.slug}",
        _bind(create_one, _kind.slug),
        methods=["POST"],
        include_in_schema=False,
        name=f"console_create_{_kind.slug}",
    )
    router.add_api_route(
        f"/{_kind.slug}/{{identifier:int}}/rename",
        _bind(rename_one, _kind.slug),
        methods=["POST"],
        include_in_schema=False,
        name=f"console_rename_{_kind.slug}",
    )
    router.add_api_route(
        f"/{_kind.slug}/{{identifier:int}}/delete",
        _bind(delete_one, _kind.slug),
        methods=["POST"],
        include_in_schema=False,
        name=f"console_delete_{_kind.slug}",
    )
