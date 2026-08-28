"""Working out what a spreadsheet is, and which column is which.

Real files are not written to a schema. The same column is `Room`, `Room name`, `room_no`
or `Code` depending on who typed it, and the sheet itself is titled nothing useful. So
both are guessed — and, because a guess is a guess, both are **reported and overridable**
rather than applied silently.

Nothing here decides that a guess is good enough. `detect` returns what it found and how
confident it is; refusing an ambiguous file is a decision for the caller, who is the one
who can ask a person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from enum import StrEnum


class Kind(StrEnum):
    """What a sheet is a list of.

    These are the four things a project is built out of by hand, and so the four worth
    importing. Terms, offerings and weekly patterns are deliberately absent: they are
    structure rather than inventory, they are few, and each one is a decision rather than
    a row.
    """

    ROOMS = "rooms"
    INSTRUCTORS = "instructors"
    COURSES = "courses"
    GROUPS = "groups"


@dataclass(frozen=True)
class Field:
    """One field of a kind, and the header names people actually write for it."""

    name: str
    aliases: tuple[str, ...]
    required: bool = False
    #: Several source columns may feed one field — a sheet with `Equipment 1`, `Equipment 2`.
    repeatable: bool = False


@dataclass(frozen=True)
class Shape:
    kind: Kind
    fields: tuple[Field, ...]

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.required)


def shape_for(kind: Kind) -> Shape:
    """The fields a kind is made of.

    Published so a client can offer the choices rather than carrying its own copy of them.
    The alternative is a list of field names per kind written in Swift, which is the second
    statement of a rule that Decision #5 forbids and which drifts the first time a field is
    added here.
    """
    return next(shape for shape in SHAPES if shape.kind is kind)


SHAPES: tuple[Shape, ...] = (
    Shape(
        Kind.ROOMS,
        (
            Field("name", ("room", "room name", "room no", "room number", "code", "label"), True),
            Field("capacity", ("seats", "size", "places", "max", "capacity"), True),
            Field("building", ("block", "wing", "site", "location")),
            Field("features", ("equipment", "facilities", "requires", "feature"), repeatable=True),
        ),
    ),
    Shape(
        Kind.INSTRUCTORS,
        (
            Field(
                "name", ("instructor", "staff", "teacher", "lecturer", "faculty", "full name"), True
            ),
            Field("email", ("e-mail", "mail", "address")),
            Field("department", ("dept", "school", "faculty of")),
        ),
    ),
    Shape(
        Kind.COURSES,
        (
            Field("code", ("course code", "subject code", "module code", "course"), True),
            Field("name", ("title", "course name", "subject", "module"), True),
            Field("credits", ("credit", "weight", "units")),
            Field("department", ("dept", "school", "owner")),
        ),
    ),
    Shape(
        Kind.GROUPS,
        (
            Field("name", ("group", "batch", "intake", "class", "section", "cohort"), True),
            Field("size", ("students", "headcount", "strength", "count")),
            Field("parent", ("parent group", "belongs to", "part of", "under")),
            Field("program", ("programme", "degree", "course of study")),
        ),
    ),
)

BY_KIND = {shape.kind: shape for shape in SHAPES}


@dataclass(frozen=True)
class Detection:
    kind: Kind | None
    #: Source column -> field name. What the report shows and the caller may override.
    mapping: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    unmatched: tuple[str, ...] = ()

    @property
    def confident(self) -> bool:
        return self.kind is not None and not self.missing


def normalise(header: str) -> str:
    """`Room  No.` and `room_no` are the same column to everyone except a computer."""
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def _matches(header: str, spec: Field) -> bool:
    wanted = normalise(header)
    if not wanted:
        return False
    candidates = {normalise(spec.name), *(normalise(a) for a in spec.aliases)}
    if wanted in candidates:
        return True
    # `Equipment 2` feeds `features`, so a trailing number is ignored for repeatables.
    if spec.repeatable:
        stripped = re.sub(r"\s*\d+$", "", wanted)
        return stripped in candidates
    return False


def _map_to(shape: Shape, headers: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    for header in headers:
        for spec in shape.fields:
            if _matches(header, spec):
                # First column wins a non-repeatable field: a sheet with two `Name`
                # columns is reported as duplicated rather than silently using the last.
                if spec.repeatable or spec.name not in mapping.values():
                    mapping[header] = spec.name
                break
    missing = [name for name in shape.required if name not in mapping.values()]
    return mapping, missing


def detect(headers: tuple[str, ...]) -> Detection:
    """Guess the kind and the columns, preferring the shape that fits best.

    Scored by how many *required* fields are matched, then by total matches, so a room
    sheet with a `Department` column is not mistaken for a course sheet because both have
    a `Name`.
    """
    best: Detection | None = None
    best_score = (-1, -1)

    for shape in SHAPES:
        mapping, missing = _map_to(shape, headers)
        score = (len(shape.required) - len(missing), len(mapping))
        if score > best_score:
            best_score = score
            best = Detection(
                kind=shape.kind,
                mapping=mapping,
                missing=tuple(missing),
                unmatched=tuple(h for h in headers if h not in mapping),
            )

    if best is None or best_score[0] <= 0:  # pragma: no cover - SHAPES is never empty
        return Detection(kind=None, unmatched=headers)
    return best


def suggest_column(header: str, kind: Kind) -> str:
    """The field a stray column most resembles, for the report to offer.

    Offered, never applied: a header the importer half-recognises is exactly where a
    silent guess turns into data nobody can account for later.
    """
    shape = BY_KIND[kind]
    vocabulary = {
        normalise(alias): spec.name for spec in shape.fields for alias in (spec.name, *spec.aliases)
    }
    close = get_close_matches(normalise(header), list(vocabulary), n=1, cutoff=0.75)
    return vocabulary[close[0]] if close else ""
