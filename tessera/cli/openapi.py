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

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def build_spec() -> dict[str, object]:
    engine = create_memory_engine()
    create_all(engine)
    try:
        return create_app(engine=engine, configure_logs=False).openapi()
    finally:
        engine.dispose()


def main() -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(build_spec(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {SNAPSHOT.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
