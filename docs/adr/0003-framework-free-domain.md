# ADR-0003: The domain layer imports no framework, enforced in CI

**Status:** Accepted · **Date:** 2026-08-07

## Context

Frameworks are the shortest-lived part of any codebase. The model of what a timetable
*is* — sessions, rooms, groups, constraints — will outlast FastAPI, SQLAlchemy, the
macOS client, and possibly the choice of Python.

Layer boundaries maintained by convention erode. Each individual violation is
convenient and locally reasonable.

## Decision

`tessera/domain/` imports only the standard library and Pydantic. Never FastAPI,
SQLAlchemy, OR-Tools, ReportLab or Jinja2. This is enforced by **import-linter** in CI
and by a runtime test, so a violation fails the build rather than being noticed in
review or not at all.

## Consequences

- Persistence and transport concerns cannot leak into the model. Some mapping code is
  required as a result, which is the price.
- The domain and its validator stay portable if any surrounding technology changes.
- Verified to fail correctly: injecting `import sqlalchemy` into the domain is rejected
  by both the static contract and the runtime guard, each naming the file and line.
