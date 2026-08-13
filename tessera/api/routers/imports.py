"""Spreadsheet and competition-format import.

Two-step by design: a dry run reports what would happen, and a second call commits.
Nobody hand-types two hundred rooms, and an import that fails halfway with no way to see
why is where most tools lose their users.

The two steps run **the same code**. A dry run parses, detects, maps, resolves every
reference, validates every row and performs every write — then rolls back. A dry run that
checked less than the commit would be worse than none, because it would turn "I checked"
into confidence nobody had earned.
"""

from __future__ import annotations

import json
import uuid
from collections import OrderedDict

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from pydantic import BaseModel, Field

from tessera.api.deps import Db
from tessera.api.errors import ERROR_BASE, ProblemError, problem_responses
from tessera.api.routers._stubs import pending
from tessera.importers import plan as planner
from tessera.importers.detect import detect
from tessera.importers.sheet import UnreadableFileError, read
from tessera.repository import imports as repo

router = APIRouter(prefix="/api/v1/imports", tags=["import"])
ERRORS = problem_responses(400, 404, 422, 501)


class ImportRowProblem(BaseModel):
    row: int
    column: str = ""
    message: str
    suggestion: str = Field(default="", description="Proposed correction, where one exists.")


class ImportReport(BaseModel):
    import_id: str
    committed: bool = Field(description="False for a dry run.")
    detected_kind: str = Field(default="", description="rooms, instructors, courses, groups.")
    rows_total: int = 0
    rows_ready: int = 0
    problems: list[ImportRowProblem] = Field(default_factory=list)
    column_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Source column to model field, guessed and then editable.",
    )


#: Recent reports, so `GET /imports/{id}` can answer.
#:
#: In memory rather than in the project file: a report is about a file that is not part
#: of the project, it is worthless once the spreadsheet has been corrected, and writing
#: it would put transient workflow state into a document people email to each other.
#: Bounded because the engine outlives many imports and none of them are large.
_REPORTS: OrderedDict[str, ImportReport] = OrderedDict()
_REPORTS_KEPT = 20


def _remember(report: ImportReport) -> ImportReport:
    _REPORTS[report.import_id] = report
    while len(_REPORTS) > _REPORTS_KEPT:
        _REPORTS.popitem(last=False)
    return report


def _unreadable(detail: str) -> ProblemError:
    return ProblemError(
        status_code=status.HTTP_400_BAD_REQUEST,
        title="The file could not be read",
        detail=detail,
        error_type=f"{ERROR_BASE}/unreadable-file",
    )


@router.post(
    "/spreadsheet",
    response_model=ImportReport,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
def import_spreadsheet(
    term_id: int,
    db: Db,
    file: UploadFile = File(description="An .xlsx or .csv file."),
    dry_run: bool = Query(default=True, description="Report only; write nothing."),
    mapping: str = Form(
        default="",
        description=(
            "JSON object of source column to model field, overriding what was detected. "
            "Send back a corrected `column_mapping` from a dry run."
        ),
    ),
) -> ImportReport:
    """Read a spreadsheet, and either report on it or apply it.

    `term_id` names the institution rather than scoping the data: rooms and staff belong
    to an institution, not a term, but a project file may hold more than one institution
    and `Block A` at one is not `Block A` at the other.
    """
    try:
        sheet = read(file.file.read(), file.filename or "upload.csv")
    except UnreadableFileError as error:
        raise _unreadable(str(error)) from error

    found = detect(sheet.headers)
    if found.kind is None:
        raise _unreadable("The columns do not look like rooms, instructors, courses or groups.")

    columns = dict(found.mapping)
    if mapping:
        try:
            columns = {str(k): str(v) for k, v in json.loads(mapping).items()}
        except (ValueError, AttributeError) as error:
            raise _unreadable("The column mapping was not a JSON object.") from error

    known = repo.catalogue_for(db, term_id)
    built = planner.build(sheet, found.kind, columns, known)
    outcome = repo.apply(db, built, dry_run=dry_run)

    problems = [
        ImportRowProblem(
            row=problem.row,
            column=problem.column,
            message=problem.message,
            suggestion=problem.suggestion,
        )
        for problem in (*built.problems, *outcome.problems)
    ]
    if found.missing:
        problems.insert(
            0,
            ImportRowProblem(
                row=1,
                column="",
                message=f"No column was found for: {', '.join(found.missing)}.",
            ),
        )

    return _remember(
        ImportReport(
            import_id=uuid.uuid4().hex[:12],
            committed=not dry_run and not outcome.rolled_back,
            detected_kind=str(found.kind),
            rows_total=built.rows_total,
            # What *would* be written. A commit that rolled back reports the same number
            # with `committed` false, rather than pretending nothing was ever viable.
            rows_ready=built.rows_ready,
            problems=problems,
            column_mapping=columns,
        )
    )


@router.post(
    "/itc", response_model=ImportReport, status_code=status.HTTP_202_ACCEPTED, responses=ERRORS
)
async def import_itc(
    file: UploadFile = File(description="An ITC-2019 XML instance."),
    dry_run: bool = Query(default=True),
) -> ImportReport:
    """Load a competition instance.

    Real institutional data to develop against before any is supplied, and a check that
    the schema generalises beyond the institution it was designed around.
    """
    pending("2.7", "ITC import")


@router.get("/{import_id}", response_model=ImportReport, responses=ERRORS)
def get_import(import_id: str) -> ImportReport:
    """A report from earlier in this session.

    Reports do not survive a restart, and should not: by then the spreadsheet has either
    been corrected or abandoned, and a stale list of problems about a file nobody has any
    more is worse than nothing.
    """
    report = _REPORTS.get(import_id)
    if report is None:
        raise ProblemError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such import",
            detail="That report is not from this session, or has aged out.",
            error_type=f"{ERROR_BASE}/not-found",
        )
    return report
