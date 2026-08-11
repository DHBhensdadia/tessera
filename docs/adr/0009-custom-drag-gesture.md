# ADR-0009: Custom DragGesture rather than draggable/dropDestination

**Status:** Accepted · **Date:** 2026-08-07

## Context

SwiftUI's `.draggable()` and `.dropDestination()` are the modern, idiomatic API for
drag and drop. They are designed for transferring items between views and applications.

Unlike in a `List`, `dropDestination` has no clean way to report *which discrete grid
cell* a drop landed on — and live conflict highlighting needs the cell under the cursor
continuously, not just at drop.

## Decision

Implement dragging with a custom `DragGesture` over a computed layout: hit-test against
our own geometry in `onChanged`, commit in `onEnded`.

## Consequences

- Full control over snapping, ghost previews, animation, and per-cell highlighting.
- Live pre-drop validation becomes possible, which is one of the four features that
  distinguish this project.
- More code than the idiomatic API, and system drag between applications is not
  supported. Neither is needed.
