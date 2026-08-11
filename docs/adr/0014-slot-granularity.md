# ADR-0014: 30-minute slots by default, configurable per project

**Status:** Accepted · **Date:** 2026-08-09

## Context

ADR-0005 fixes time to an integer grid, which forces a choice of resolution. Halving the
slot doubles the number of periods and therefore the size of the model.

Measuring on CB-CTT suggested a finer grid was free — solve time *fell* at 2× and 4×
resolution. That result is confounded and was not used: in CB-CTT every lecture occupies
exactly one period, so extra periods add genuine freedom. Tessera's sessions have
durations, so a finer grid describes the same day more precisely without adding any
freedom. It is pure cost.

## Decision

Default to **30-minute slots**, stored as `slot_minutes` on the project and chosen at
creation time. **15-minute grids remain available.**

## Consequences

- 30 minutes halves the model against 15 and matches how most institutions schedule.
- 15 minutes must stay available because a **45-minute period cannot be represented on
  a 30-minute grid at all**, and 45- and 50-minute lectures are common in Indian
  universities, which are squarely the target users.
- The choice is per project because it is an institutional fact, not a global constant.
- It cannot be changed after creation without re-slotting every assignment, so the
  project-creation flow presents it deliberately, with a live preview of the resulting
  week.
