# ADR-0011: Apple Silicon only; no Intel build

**Status:** Accepted · **Date:** 2026-08-08

## Context

The plan originally assumed a universal `.dmg` carrying both architectures. Phase 0.3
established that this is not achievable from one build: **PyInstaller cannot
cross-compile**, freezing instead against the host's installed wheels, and OR-Tools
ships architecture-specific ones.

The options were two `.dmg` files built on native CI runners, fragile universal2 wheel
juggling, or arm64 only.

## Decision

Build for **arm64 only**, one artefact. Intel Macs are out of scope.

## Consequences

- CI needs one runner rather than two, and the release page carries one file.
- Intel Mac users cannot run the application. They can run the engine via Docker or the
  CLI, and read exported HTML.
- Reversible: adding an `x86_64` job restores an Intel build. The architecture does not
  change, only the build matrix.
