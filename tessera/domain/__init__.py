"""The model, and the rules that decide whether a timetable is valid.

This layer imports no framework — not FastAPI, not SQLAlchemy, not OR-Tools. That
constraint is enforced in CI by import-linter, and it is what keeps the domain
portable if any surrounding technology is replaced (ADR-003).

The constraint validator lives here rather than in the solver because both the solver
and the drag-and-drop UI must reach the same verdict about the same move. Two
implementations would drift (ADR-004).
"""
