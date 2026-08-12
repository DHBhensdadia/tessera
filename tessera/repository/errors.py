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
