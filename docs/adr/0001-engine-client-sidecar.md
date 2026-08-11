# ADR-0001: Python engine and SwiftUI client, joined by a loopback sidecar

**Status:** Accepted · **Date:** 2026-08-07

## Context

Two requirements pulled against each other. The application must be a single
self-contained `.dmg` that runs offline and leaves nothing behind when deleted. It must
also be built on a real HTTP API and database, because the engine needs to be reusable
outside macOS and because that is the honest way to build this.

A monolithic Swift application satisfies the first and forecloses the second. A
client/server deployment satisfies the second and ruins the first.

## Decision

Ship a Python engine, frozen with PyInstaller, inside the `.app` bundle. The SwiftUI
client spawns it on launch; the engine binds an ephemeral port on `127.0.0.1`, prints a
JSON handshake carrying its port and a per-launch token, and exits when its parent does.

The engine is the entire product. The client renders and edits; it owns no business
logic.

## Consequences

- One codebase ships three ways: bundled in the `.dmg`, as a Docker image, and as a
  CLI. Linux and Windows users get the engine even though the editor is macOS-only.
- The `.dmg` grows by roughly 150 MB, dominated by OR-Tools.
- Subprocess lifecycle becomes our problem: orphan prevention, crash surfacing, and
  startup failure all need explicit handling.
- Every client action costs a round trip. Measured in Phase 0.2 at 0.68 ms p99, against
  a 16 ms frame budget.
