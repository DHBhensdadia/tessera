"""Importing a spreadsheet in a browser.

The one page in the console with two steps. Upload produces a **report** and writes
nothing; the report is read, the column mapping corrected if the guess was wrong, and
only then is anything committed.

That shape is the whole feature. An importer that writes on upload and explains
afterwards is one people stop trusting the first time it is wrong about a file they cared
about.

The uploaded bytes are held between the two steps so that committing does not mean
finding the file again — a step that, on the second attempt after fixing a mapping, is
exactly where somebody gives up. They live in memory, bounded, alongside the report:
neither belongs in a project file that gets emailed to other people.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.importers import plan as planner
from tessera.importers.detect import BY_KIND, Kind, detect, suggest_column
from tessera.importers.sheet import UnreadableFileError, read
from tessera.repository import calendar as calendar_repo
from tessera.repository import imports as repo
from tessera.repository.errors import RepositoryError

#: Uploads waiting for a decision. Small, bounded, and gone when the engine stops —
#: a spreadsheet somebody is halfway through checking is not part of their project.
_PENDING: OrderedDict[str, Upload] = OrderedDict()
_KEPT = 10


@dataclass(frozen=True)
class Upload:
    data: bytes
    filename: str
    term_id: int
    kind: Kind
    mapping: dict[str, str]


def _remember(upload: Upload) -> str:
    token = uuid4().hex[:12]
    _PENDING[token] = upload
    while len(_PENDING) > _KEPT:
        _PENDING.popitem(last=False)
    return token


def _fields_for(kind: Kind) -> tuple[str, ...]:
    """Every field this kind of sheet has, for the correction dropdowns."""
    return tuple(field.name for field in BY_KIND[kind].fields)


def _render(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    return page(
        request,
        "imports/upload.html",
        terms=calendar_repo.list_terms(db),
        problem=problem,
        **extra,
    )


@router.get("/imports", include_in_schema=False)
def upload_form(request: Request, db: Db) -> HTMLResponse:
    return _render(request, db)


@router.post("/imports", include_in_schema=False)
def check_upload(
    request: Request, db: Db, term_id: int = Form(...), file: UploadFile = Form(...)
) -> Response:
    """Read the file and report on it. Nothing is written."""
    data = file.file.read()
    try:
        sheet = read(data, file.filename or "upload.csv")
    except UnreadableFileError as error:
        return _render(request, db, problem=str(error))

    found = detect(sheet.headers)
    if found.kind is None:
        return _render(
            request,
            db,
            problem="These columns do not look like rooms, instructors, courses or groups.",
        )

    known = repo.catalogue_for(db, term_id)
    built = planner.build(sheet, found.kind, found.mapping, known)
    outcome = repo.apply(db, built, dry_run=True)

    token = _remember(
        Upload(
            data=data,
            filename=file.filename or "upload.csv",
            term_id=term_id,
            kind=found.kind,
            mapping=dict(found.mapping),
        )
    )
    return _report(request, db, token, built, outcome, found.missing, sheet.headers)


def _report(
    request: Request,
    db: Db,
    token: str,
    built: planner.Plan,
    outcome: repo.Outcome,
    missing: tuple[str, ...],
    headers: tuple[str, ...],
    problem: str | None = None,
) -> HTMLResponse:
    upload = _PENDING[token]
    return _render(
        request,
        db,
        token=token,
        filename=upload.filename,
        kind=str(built.kind),
        rows_total=built.rows_total,
        rows_ready=built.rows_ready,
        problems=[*built.problems, *outcome.problems],
        missing=missing,
        # Every column of the file, so a wrong guess can be repointed and an unrecognised
        # column can be given a field rather than silently ignored.
        columns=[
            {
                "header": header,
                "field": built.mapping.get(header, ""),
                "suggestion": suggest_column(header, built.kind)
                if header not in built.mapping
                else "",
            }
            for header in headers
        ],
        fields=_fields_for(built.kind),
        problem=problem,
    )


@router.post("/imports/{token}/check", include_in_schema=False)
async def recheck(request: Request, db: Db, token: str) -> Response:
    """Report again with a corrected mapping, still writing nothing."""
    return await _rerun(request, db, token, commit=False)


@router.post("/imports/{token}/commit", include_in_schema=False)
async def commit(request: Request, db: Db, token: str) -> Response:
    return await _rerun(request, db, token, commit=True)


async def _rerun(request: Request, db: Db, token: str, *, commit: bool) -> Response:
    """Run the stored file again, with whatever mapping the form now says.

    The same path serves "check again" and "import": the only difference is whether the
    savepoint is released, which is what makes the report a promise rather than a guess.
    """
    upload = _PENDING.get(token)
    if upload is None:
        return _render(request, db, problem="That upload has expired. Choose the file again.")

    form = await request.form()
    mapping = {
        str(key)[len("column:") :]: str(value)
        for key, value in form.items()
        if str(key).startswith("column:") and value
    }

    sheet = read(upload.data, upload.filename)
    known = repo.catalogue_for(db, upload.term_id)
    built = planner.build(sheet, upload.kind, mapping or upload.mapping, known)

    try:
        outcome = repo.apply(db, built, dry_run=not commit)
    except RepositoryError as error:
        return _report(
            request, db, token, built, repo.Outcome(), (), sheet.headers, problem=describe(error)
        )

    if commit and not outcome.rolled_back:
        _PENDING.pop(token, None)
        return redirect(f"/console/{_section_for(built.kind)}")
    return _report(request, db, token, built, outcome, (), sheet.headers)


def _section_for(kind: Kind) -> str:
    """Where to land after importing, so the result is visible rather than asserted."""
    return {
        Kind.ROOMS: "rooms",
        Kind.INSTRUCTORS: "instructors",
        Kind.COURSES: "courses",
        Kind.GROUPS: "student-groups",
    }[kind]
