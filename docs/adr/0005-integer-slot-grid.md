# ADR-0005: Time is an integer slot index, never a timestamp

**Status:** Accepted · **Date:** 2026-08-07

## Context

Timetables are full of time arithmetic: does this session overlap that one, is this
inside the lunch break, are these two adjacent. Expressed with datetimes, each of these
is an interval comparison with edge cases.

## Decision

The week is a fixed grid of atomic slots. A session occupies a start index and a
duration in slots. Day and slot-of-day are recovered by division. Human-readable times
are display metadata, derived from `slot_minutes` on the project.

## Consequences

- Overlap detection becomes integer arithmetic, trivially correct and fast enough that
  the solver can do it millions of times.
- The grid resolution is fixed per project at creation and cannot be changed afterwards
  without re-slotting every assignment. This is surfaced in the project-creation flow
  as a deliberate, explained choice.
- Sessions cannot start off-grid. A 45-minute lecture requires a 15-minute grid; it
  cannot be represented on a 30-minute one. See ADR-0014.
