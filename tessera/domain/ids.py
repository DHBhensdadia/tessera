"""Typed identifiers.

Every entity gets its own integer alias rather than a bare ``int``. The runtime
representation is identical, but mypy will reject passing a ``RoomId`` where a
``SessionId`` is expected — which in a model with twenty entity types is a class of
bug that is otherwise found only by reading carefully.
"""

from __future__ import annotations

from typing import NewType

InstitutionId = NewType("InstitutionId", int)
DepartmentId = NewType("DepartmentId", int)
BuildingId = NewType("BuildingId", int)
FeatureId = NewType("FeatureId", int)
RoomId = NewType("RoomId", int)
InstructorId = NewType("InstructorId", int)
ProgramId = NewType("ProgramId", int)
StudentGroupId = NewType("StudentGroupId", int)
CourseId = NewType("CourseId", int)
TimeGridId = NewType("TimeGridId", int)
TermId = NewType("TermId", int)
OfferingId = NewType("OfferingId", int)
SessionTemplateId = NewType("SessionTemplateId", int)
SessionId = NewType("SessionId", int)
TimetableId = NewType("TimetableId", int)
AssignmentId = NewType("AssignmentId", int)
ConstraintId = NewType("ConstraintId", int)
CommandId = NewType("CommandId", int)
