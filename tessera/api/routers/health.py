"""Health and metadata. The only routes in Phase 1.4 that do real work.

``/health`` is what the Swift client polls after spawning the engine, so it must answer
without touching anything that could hang, and it must say whether the project database
is actually reachable rather than only that the process is up.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

import tessera
from tessera.api.deps import ProjectState, get_project

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str = Field(description="'ok' when the engine can reach its project.")
    version: str
    pid: int
    project: str
    database: str = Field(description="'connected', or the reason it is not.")


class Meta(BaseModel):
    version: str
    api_version: str
    schema_revision: str | None = Field(
        default=None, description="Alembic revision the open project is at."
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Optional features this build supports, for a client to adapt to.",
    )


@router.get("/health", response_model=Health, summary="Engine liveness")
def health(project: Annotated[ProjectState, Depends(get_project)]) -> Health:
    try:
        with project.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "connected"
        status = "ok"
    except Exception as error:
        database = f"unavailable: {type(error).__name__}"
        status = "degraded"

    return Health(
        status=status,
        version=tessera.__version__,
        pid=os.getpid(),
        project=project.name,
        database=database,
    )


@router.get("/api/v1/meta", response_model=Meta, summary="Engine and schema metadata")
def meta(project: Annotated[ProjectState, Depends(get_project)]) -> Meta:
    revision: str | None = None
    try:
        with project.engine.connect() as connection:
            row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
            revision = row[0] if row else None
    except Exception:
        revision = None

    return Meta(version=tessera.__version__, api_version="v1", schema_revision=revision)
