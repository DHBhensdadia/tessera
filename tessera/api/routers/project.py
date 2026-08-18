"""The project itself — which is to say, Save As, and nothing else.

There is no open or close endpoint here, and that is the design rather than an omission.
One engine serves one project for its whole life; the client opens a second project by
launching a second engine, which is what the 1.5 handshake was built around — *"a fixed
port … prevents two projects being open at once"*. An endpoint that swapped the project
underneath a running server would make the engine's identity mutable, invalidate every
open session, and give the token a second meaning.

Saving needs no endpoint either: SQLite commits, and P7 Act 12 is explicit that there is
no Save button and no unsaved-changes dialog.

What is left is the one project-level thing the client genuinely cannot do for itself.
Copying an open project is not a file copy — see `tessera.project.copy_to`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field

from tessera.api.deps import ProjectState, get_project
from tessera.api.errors import problem_responses
from tessera.api.schemas.common import Wire
from tessera.project import copy_to, database_path
from tessera.repository.errors import ConflictError, RuleViolationError

router = APIRouter(prefix="/api/v1", tags=["project"])
ERRORS = problem_responses(409, 422)


class ProjectCopy(Wire):
    destination: str = Field(
        min_length=1,
        description="Where to write the copy. Must not already exist.",
    )


class ProjectCopied(Wire):
    path: str


@router.post(
    "/project/copy",
    response_model=ProjectCopied,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
def copy_project(
    payload: ProjectCopy, project: Annotated[ProjectState, Depends(get_project)]
) -> ProjectCopied:
    """Save a copy of the open project, while it is open.

    A snapshot rather than a byte copy, because with WAL the file on disk is not the
    whole database. The original keeps serving throughout; nothing here writes to it.
    """
    if project.path is None:
        raise RuleViolationError("this engine has no project on disk to copy")

    destination = Path(payload.destination).expanduser()
    try:
        written = copy_to(database_path(project.path), destination)
    except FileExistsError as error:
        # Refused rather than overwritten. "Save a copy" onto something that exists is
        # how a user loses the thing they were copying *to*, and the engine has no way
        # to ask whether they meant it.
        raise ConflictError(f"{destination} already exists") from error
    return ProjectCopied(path=str(written))
