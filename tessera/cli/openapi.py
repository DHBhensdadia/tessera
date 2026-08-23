"""Regenerate the committed OpenAPI snapshot.

The contract test compares the live application against `docs/openapi.json`. When a
change to the surface is intentional, this is how the snapshot is brought back into
agreement — an explicit step, so that a contract change is always a deliberate commit
rather than a side effect of editing a router.
"""

from __future__ import annotations

import json
from pathlib import Path

from tessera.api import create_app
from tessera.repository import create_all, create_memory_engine

ROOT = Path(__file__).resolve().parents[2]

#: The snapshot the contract test compares against, and the one people read.
SNAPSHOT = ROOT / "docs" / "openapi.json"

#: The same document, inside the Swift package.
#:
#: Not a second source of truth — a second *copy*, which is worse if nothing enforces it.
#: SwiftPM plugins are sandboxed to their package directory, so the generator cannot read
#: `docs/`, and a symlink survives git but not a zip, a Docker build context, or a Windows
#: checkout of a repository that advertises a Docker image. So both are written here, in
#: one function, and `scripts/check.sh` fails if they ever differ.
CLIENT_COPY = ROOT / "client" / "Sources" / "EngineClient" / "openapi.json"


def build_spec() -> dict[str, object]:
    engine = create_memory_engine()
    create_all(engine)
    try:
        return create_app(engine=engine, configure_logs=False).openapi()
    finally:
        engine.dispose()


def main() -> None:
    document = json.dumps(build_spec(), indent=2, sort_keys=True) + "\n"
    for destination in (SNAPSHOT, CLIENT_COPY):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document)
        print(f"wrote {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
