"""Dependencies: the open project, and a database session per request.

The engine serves exactly one project — the file the user opened (Decision #25, and D1
of the Phase 1.4 plan) — so the project is process state rather than a URL parameter.
It is held here and injected, rather than reached for as a global, so that tests can
supply their own without touching the module.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from tessera.api.errors import ERROR_BASE, ProblemError


@dataclass
class ProjectState:
    """The open project. Created at startup and attached to the application."""

    engine: Engine
    path: Path | None
    sessions: sessionmaker[DbSession]

    @property
    def name(self) -> str:
        return self.path.stem if self.path else "untitled"


def get_project(request: Request) -> ProjectState:
    state: ProjectState | None = getattr(request.app.state, "project", None)
    if state is None:
        raise ProblemError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="No project open",
            detail="The engine started without a project file.",
            error_type=f"{ERROR_BASE}/no-project",
        )
    return state


def get_db(
    project: Annotated[ProjectState, Depends(get_project)],
) -> Iterator[DbSession]:
    """One session per request, committed on success and rolled back on failure.

    Rolling back on *any* exception matters more than it looks: without it a failed
    request can leave a partial write visible to the next one, which is how a rejected
    import ends up half-applied.
    """
    session = project.sessions()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


Project = Annotated[ProjectState, Depends(get_project)]
Db = Annotated[DbSession, Depends(get_db)]
