"""Spreadsheet and competition-format import.

Two-step by design: a dry run reports what would happen, and a second call commits.
Nobody hand-types two hundred rooms, and an import that fails halfway with no way to see
why is where most tools lose their users.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile, status
from pydantic import BaseModel, Field

from tessera.api.errors import problem_responses
from tessera.api.routers._stubs import pending

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


@router.post(
    "/spreadsheet",
    response_model=ImportReport,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
)
async def import_spreadsheet(
    term_id: int,
    file: UploadFile = File(description="An .xlsx or .csv file."),
    dry_run: bool = Query(default=True, description="Report only; write nothing."),
) -> ImportReport:
    pending("2.6", "Spreadsheet import")


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
    pending("2.6")
