#!/usr/bin/env python3
"""Every property the contract declares reaches the generated Swift, or this fails.

The generator drops what it cannot map, silently, and produces code that compiles. Every
`*Update` model in this API generated as an **empty struct** — so nothing could be edited
through the typed client, and neither the compiler, the suites, nor a probe that only
created and listed had anything to say about it.

That was fixed by rewriting Pydantic's `anyOf: [X, null]` into 3.1's `type: [X, "null"]`.
This exists so the next unmappable shape is loud instead.

Known gaps are listed rather than tolerated in silence: a nullable `$ref` is still dropped,
which costs ten display-only fields. Adding to that list should feel like a decision.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "openapi.json"
GENERATED = (
    ROOT
    / "client/.build/plugins/outputs/client/EngineClient/destination"
    / "OpenAPIGenerator/GeneratedSources/Types.swift"
)

#: Properties the generator cannot express, with a reason each.
#:
#: Empty, and worth keeping that way. It held ten nullable `$ref`s until 3.4 part 2 —
#: `RoomRead.building` and its kind — which were dropped because a `$ref` has no `type` to
#: move into a nullable array. Inlining the referenced schema is the spelling the generator
#: maps, so they are all reachable now. Adding to this list should feel like a decision.
KNOWN_GAPS: dict[str, set[str]] = {}


def generated_properties(source: str, name: str) -> set[str] | None:
    """The property names on one generated struct, by matching braces.

    Reading a fixed number of characters after the declaration is not good enough — it
    truncates the larger models and reports properties as missing that are simply further
    down. That produced a false alarm about `ConstraintUpdate` before this was written.
    """
    match = re.search(rf"public struct {re.escape(name)}: Codable, Hashable, Sendable \{{", source)
    if match is None:
        return None
    depth, index = 1, match.end()
    while depth and index < len(source):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        index += 1
    # `type` and friends are escaped to `_type` rather than dropped; treat them as present.
    found = re.findall(r"public var (\w+):", source[match.end() : index])
    return {name.lstrip("_") for name in found}


def main() -> None:
    if not GENERATED.exists():
        sys.exit(f"no generated sources at {GENERATED.relative_to(ROOT)} — build the client first")

    schemas = json.loads(SPEC.read_text())["components"]["schemas"]
    source = GENERATED.read_text()

    surprises: list[str] = []
    for name, schema in schemas.items():
        declared = set(schema.get("properties", {}))
        if not declared:
            continue
        produced = generated_properties(source, name)
        if produced is None:
            continue
        missing = declared - produced - KNOWN_GAPS.get(name, set())
        if missing:
            surprises.append(f"  {name}: {sorted(missing)}")

    if surprises:
        sys.exit(
            "the generator dropped properties the contract declares:\n"
            + "\n".join(surprises)
            + "\nThese are unreachable from Swift. Either give the schema a spelling the "
            "generator maps, or add it to KNOWN_GAPS with a reason."
        )

    stale = {n: sorted(p) for n, p in KNOWN_GAPS.items() if n not in schemas}
    if stale:
        sys.exit(f"KNOWN_GAPS names schemas that no longer exist: {stale}")


if __name__ == "__main__":
    main()
