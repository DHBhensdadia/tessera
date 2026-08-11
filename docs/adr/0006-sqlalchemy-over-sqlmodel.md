# ADR-0006: SQLAlchemy 2.0 rather than SQLModel

**Status:** Accepted · **Date:** 2026-08-07

## Context

SQLModel is written by FastAPI's author and merges ORM and API schema into one model,
removing duplication and reading very well in FastAPI applications.

## Decision

Use SQLAlchemy 2.0 with typed `Mapped[]` declarations, and separate Pydantic schemas
for the API.

## Consequences

- Self-referential trees (student groups), many-to-many joins with payloads, and
  polymorphic constraints are exactly where SQLModel's abstraction thins out and one
  ends up at SQLAlchemy anyway, with an extra layer in between.
- The API contract and the database schema stay **deliberately separate**. Three
  consumers depend on the wire format; a table change must not silently become a
  breaking API change.
- The cost is duplication between mapped classes and schemas. In a project with a
  published API, that separation is the point rather than an inconvenience.
