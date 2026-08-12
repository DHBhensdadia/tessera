"""Error responses, in RFC 9457 Problem Details form.

FastAPI's default is ``{"detail": "some string"}``, which is not enough for the errors
this application actually raises. A spreadsheet import fails on row 14 *and* row 88 for
different reasons; an infeasible term fails because three specific constraints cannot
coexist. Both need structure, and the client needs one shape to decode rather than a
different one per endpoint.

    {
      "type":     "https://tessera.dev/errors/validation-failed",
      "title":    "Validation failed",
      "status":   422,
      "detail":   "2 rows could not be imported",
      "instance": "/api/v1/imports/spreadsheet",
      "errors":   [{"pointer": "rows/14/feature", "message": "unknown feature"}]
    }

``errors`` is an RFC 9457 extension member: the specification explicitly allows them,
and every real API needs somewhere to put field-level detail.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tessera.repository.errors import ConflictError, InvalidReferenceError, NotFoundError

logger = structlog.get_logger(__name__)

ERROR_BASE = "https://tessera.dev/errors"
CONTENT_TYPE = "application/problem+json"


class ErrorDetail(BaseModel):
    """One specific thing that was wrong, located precisely enough to act on."""

    pointer: str = Field(
        default="",
        description="JSON Pointer to the offending value, e.g. 'rows/14/capacity'.",
    )
    message: str
    hint: str = Field(default="", description="Suggested correction, where one exists.")


class Problem(BaseModel):
    """RFC 9457 Problem Details. The single error shape for the whole API."""

    type: str = Field(description="Stable URI identifying the kind of problem.")
    title: str = Field(description="Short, human-readable, constant per type.")
    status: int
    detail: str = Field(default="", description="Explanation of this occurrence.")
    instance: str = Field(default="", description="Path that produced it.")
    errors: list[ErrorDetail] = Field(default_factory=list)


class ProblemError(Exception):
    """Raise to return a Problem. The application's own error type."""

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str = "",
        error_type: str = "about:blank",
        errors: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.error_type = error_type
        self.errors = errors or []

    def to_problem(self, instance: str = "") -> Problem:
        return Problem(
            type=self.error_type,
            title=self.title,
            status=self.status_code,
            detail=self.detail,
            instance=instance,
            errors=self.errors,
        )


class NotImplementedYetError(ProblemError):
    """A route that exists on purpose but has no implementation yet.

    The contract is frozen in Phase 1.4 before the handlers are written, so these routes
    are real and discoverable. 501 rather than 404 because the distinction matters: 404
    would say the endpoint does not exist, when the point is that it does and its shape
    is already agreed.
    """

    def __init__(self, phase: str, what: str = "") -> None:
        super().__init__(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            title="Not implemented yet",
            detail=f"{what or 'This endpoint'} is implemented in phase {phase}.",
            error_type=f"{ERROR_BASE}/not-implemented",
        )
        self.phase = phase


def problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(),
        media_type=CONTENT_TYPE,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Route every failure through the same envelope.

    Including the ones raised by the framework rather than by us: a client that has to
    decode two different error shapes will eventually mishandle one of them.
    """

    @app.exception_handler(ProblemError)
    async def _handle_problem(request: Request, exc: ProblemError) -> JSONResponse:
        if exc.status_code >= 500 and not isinstance(exc, NotImplementedYetError):
            logger.error("request_failed", path=request.url.path, title=exc.title)
        return problem_response(exc.to_problem(instance=request.url.path))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(
                pointer="/".join(str(part) for part in error["loc"]),
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/validation-failed",
                title="Validation failed",
                status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{len(details)} field(s) failed validation",
                instance=request.url.path,
                errors=details,
            )
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/http-{exc.status_code}",
                title=str(exc.detail),
                status=exc.status_code,
                instance=request.url.path,
            )
        )

    @app.exception_handler(NotFoundError)
    async def _handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/not-found",
                title="Not found",
                status=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
                instance=request.url.path,
            )
        )

    @app.exception_handler(ConflictError)
    async def _handle_conflict(request: Request, exc: ConflictError) -> JSONResponse:
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/conflict",
                title="ConflictError",
                status=status.HTTP_409_CONFLICT,
                detail=exc.message,
                instance=request.url.path,
                errors=[
                    ErrorDetail(pointer=kind, message=f"{count} still depend on it")
                    for kind, count in exc.blockers.items()
                    if count
                ],
            )
        )

    @app.exception_handler(InvalidReferenceError)
    async def _handle_invalid_reference(
        request: Request, exc: InvalidReferenceError
    ) -> JSONResponse:
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/invalid-reference",
                title="Unknown reference",
                status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
                instance=request.url.path,
                errors=[
                    ErrorDetail(pointer=f"body/{exc.field}", message=f"no record with id {i}")
                    for i in exc.missing
                ],
            )
        )

    @app.exception_handler(IntegrityError)
    async def _handle_integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        """A constraint the repository did not check first.

        The repository checks the common cases so it can answer in sentences, but the
        constraints are the real guarantee and can still fire — a race, or a path that
        forgot to look. Either way it is the caller's request that cannot be satisfied,
        not the engine failing, so it is a 409 rather than the 500 the catch-all below
        would otherwise produce.
        """
        logger.warning("integrity_error", path=request.url.path, error=str(exc.orig))
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/conflict",
                title="ConflictError",
                status=status.HTTP_409_CONFLICT,
                detail="This would break a rule the database enforces.",
                instance=request.url.path,
            )
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The message is deliberately not echoed to the client: an unexpected exception
        # can carry file paths or query fragments. The log keeps the detail.
        logger.exception("unhandled_exception", path=request.url.path)
        return problem_response(
            Problem(
                type=f"{ERROR_BASE}/internal",
                title="Internal error",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The engine failed to handle this request. See the engine log.",
                instance=request.url.path,
            )
        )


def problem_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI documentation for the error codes a route can return.

    Without this the generated schema claims every failure is FastAPI's default shape,
    and a client generated from it would decode errors wrongly.
    """
    return {
        code: {"model": Problem, "content": {CONTENT_TYPE: {}}, "description": _TITLES[code]}
        for code in codes
    }


_TITLES = {
    400: "Bad request",
    404: "Not found",
    409: "ConflictError",
    422: "Validation failed",
    500: "Internal error",
    501: "Not implemented yet",
}
