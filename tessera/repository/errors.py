"""Failures the repository raises, in the repository's own vocabulary.

Deliberately not HTTP errors. The repository is used by the API, the CLI and the
importers, and only one of those has status codes — raising ``HTTPException`` here would
drag FastAPI into a layer that ADR-0003 keeps free of it, and would make the same
failure meaningless to the other two callers.

The API translates these at its edge.
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Base for anything the repository refuses to do."""


class NotFoundError(RepositoryError):
    """No record with that identifier.

    Carries the kind and the id rather than a formatted sentence, so the caller can
    phrase it for its own audience — a 404 body, a CLI message, a row number in an
    import report.
    """

    def __init__(self, kind: str, identifier: int | str) -> None:
        super().__init__(f"no {kind} with id {identifier}")
        self.kind = kind
        self.identifier = identifier


class ConflictError(RepositoryError):
    """The request is coherent but the current state forbids it.

    Two cases: something already exists with that name, or something else still depends
    on what you asked to remove. ``blockers`` counts the dependants, because "cannot
    delete" is far less useful than "cannot delete: 18 assignments use it".
    """

    def __init__(self, message: str, *, blockers: dict[str, int] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.blockers = blockers or {}


class InvalidReferenceError(RepositoryError):
    """A referenced record does not exist.

    Separate from NotFoundError: the thing being *acted on* exists, but something it points
    at does not — creating a room with a feature id that was never created. Different
    fault, and the API reports it against the offending field.
    """

    def __init__(self, field: str, missing: list[int]) -> None:
        super().__init__(f"{field} references unknown ids: {sorted(missing)}")
        self.field = field
        self.missing = sorted(missing)


class RuleViolationError(RepositoryError):
    """The domain refused the request.

    Distinct from ConflictError, which is about the *state* — something already exists,
    or something still depends on it. This is about the request itself: a rule that
    cannot target what it names, a parameter outside its range. The caller has to change
    what it sent, not wait for the state to change, which is why it becomes a 422.

    ``field`` points at the part of the body that is wrong where that is knowable.
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def first_message(error: ValueError) -> str:
    """Pydantic's own text, without the type and documentation link around it.

    ``str(ValidationError)`` is four lines of machine detail. What a person needs is the
    sentence the domain wrote.
    """
    errors = getattr(error, "errors", None)
    if callable(errors):
        found = errors()
        if found:
            return str(found[0].get("msg", "")).removeprefix("Value error, ")
    return str(error)
