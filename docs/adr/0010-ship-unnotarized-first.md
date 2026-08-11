# ADR-0010: Ship unnotarized initially; add Developer ID later

**Status:** Accepted · **Date:** 2026-08-07

## Context

Distributing a macOS app without a Gatekeeper warning requires notarization, which
requires the Apple Developer Program at $99/year. Development and testing require only a
free Apple ID.

## Decision

Ship ad-hoc signed builds from the first release, documenting the first-launch
workaround in the README. Add Developer ID signing and notarization when the project
justifies the cost.

## Consequences

- Users see "Apple could not verify this app is free of malware" on first launch and
  must right-click → Open. This costs some downloads.
- Nothing architectural is deferred. Phase 0.3 already signs with Hardened Runtime and
  the entitlements PyInstaller requires, so enabling notarization changes only the
  signing identity.
