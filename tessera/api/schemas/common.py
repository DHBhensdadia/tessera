"""Shapes shared across resources."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Wire(BaseModel):
    """Base for every wire model.

    ``from_attributes`` lets a response be built directly from a domain object or an ORM
    row without an intermediate dict.
    """

    model_config = ConfigDict(from_attributes=True)


class Reference(Wire):
    """A pointer to another resource, with enough label to display without a second call.

    Returning bare ids would force the client to fetch every related name separately,
    which for a timetable grid means hundreds of requests to render one screen.
    """

    id: int
    name: str = ""


class Page[T](BaseModel):
    """A collection response.

    Envelope rather than a bare array from the start: adding pagination later (D5) then
    means new fields, not a changed response type.
    """

    items: list[T]
    total: int = Field(description="Total available, which today always equals len(items).")
