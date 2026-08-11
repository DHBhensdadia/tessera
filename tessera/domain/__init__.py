"""The domain layer: entities, the time model, and the rules that bind them.

Imports nothing framework-shaped — no FastAPI, no SQLAlchemy, no OR-Tools — and that is
enforced by import-linter and by a test rather than left as a convention. It is the part
of the codebase that survives a change of web framework, database, or desktop platform.

See ADR-0003 and docs/internals/domain-model.md.
"""

from tessera.domain.constraints import (
    Constraint,
    ConstraintKind,
    ConstraintScope,
    default_constraints,
)
from tessera.domain.entities import (
    Building,
    Course,
    Department,
    Feature,
    Institution,
    Instructor,
    Offering,
    Program,
    Room,
    Session,
    SessionKind,
    SessionTemplate,
    Term,
    Unavailability,
    UnavailabilityKind,
)
from tessera.domain.groups import GroupKind, GroupSet, StudentGroup
from tessera.domain.time_grid import Slot, TimeGrid
from tessera.domain.timetable import (
    Assignment,
    Command,
    CommandKind,
    Timetable,
    TimetableStatus,
)

__all__ = [
    "Assignment",
    "Building",
    "Command",
    "CommandKind",
    "Constraint",
    "ConstraintKind",
    "ConstraintScope",
    "Course",
    "Department",
    "Feature",
    "GroupKind",
    "GroupSet",
    "Institution",
    "Instructor",
    "Offering",
    "Program",
    "Room",
    "Session",
    "SessionKind",
    "SessionTemplate",
    "Slot",
    "StudentGroup",
    "Term",
    "TimeGrid",
    "Timetable",
    "TimetableStatus",
    "Unavailability",
    "UnavailabilityKind",
    "default_constraints",
]
