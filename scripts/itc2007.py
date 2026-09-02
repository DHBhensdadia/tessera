"""Put the ITC-2007 instances where the benchmark can read them, and prove they are the ones.

The 21 `.ctt` files are **not in this repository**. They are somebody else's data, served
openly by Queen's University Belfast, and neither that host nor the third-party mirror declares
a licence — absence of one is not permission to redistribute (4.5's D10). So they are fetched
rather than committed, and this is what fetches them.

**The checksums are already here**, in `itc2007-instances.sha256`, and have been since 4.2.
That is what makes fetching as trustworthy as committing: every number this project publishes is
attached to specific bytes, and a file that does not hash to the recorded digest is refused
rather than benchmarked.

**Two failures, and they are different facts.** A host that cannot be reached is not a fact
about this repository, so it exits `75` — the conventional "temporary failure" — and the caller
skips, saying why. A file that arrives and hashes wrong *is* a fact about this repository: some
instance has been re-issued or corrupted, and every result attached to it is void. That exits
`1`. Reporting the two the same way is what let a ten-minute CI poll masquerade as a red build
for months (#258), and it is not repeated here.

Idempotent: a file already present and already correct is left alone, so this is cheap to run
before every benchmark and cheap to cache.

    uv run python scripts/itc2007.py <directory>
"""

from __future__ import annotations

import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

#: Where 4.2 found them, recorded in plans/phase-4.2.md. The competition's own registration is
#: dead — the login page returns HTTP 500 on both hosts — and this path serves all 21 openly.
SOURCE = "https://www.eeecs.qub.ac.uk/itc2007/curriculmcourse/initialdatasets/"

CHECKSUMS = Path(__file__).parent / "itc2007-instances.sha256"

UNREACHABLE = 75
"""`EX_TEMPFAIL`. Try again later; nothing is wrong here."""

TIMEOUT = 30


def wanted() -> dict[str, str]:
    """Every instance and the digest it must have, from the file 4.2 committed."""
    digests = {}
    for line in CHECKSUMS.read_text().splitlines():
        if line.strip():
            digest, name = line.split()
            digests[name] = digest
    if len(digests) != 21:
        raise SystemExit(f"{CHECKSUMS} lists {len(digests)} instances, not 21")
    return digests


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(name: str) -> bytes:
    with urllib.request.urlopen(SOURCE + name, timeout=TIMEOUT) as response:
        return bytes(response.read())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    into = Path(argv[1]).expanduser()
    into.mkdir(parents=True, exist_ok=True)

    had, got = 0, 0
    for name, digest in sorted(wanted().items()):
        here = into / name
        if here.exists() and digest_of(here) == digest:
            had += 1
            continue
        try:
            content = fetch(name)
        except (urllib.error.URLError, TimeoutError, OSError) as unreachable:
            print(f"cannot reach {SOURCE} — {unreachable}")
            print(f"  {had} of 21 instances were already present; the rest are not")
            return UNREACHABLE

        found = hashlib.sha256(content).hexdigest()
        if found != digest:
            print(f"{name} does not hash to the digest this project recorded for it")
            print(f"  expected {digest}")
            print(f"  received {found}")
            print("  every published number attached to this instance is now in question")
            return 1

        here.write_bytes(content)
        got += 1

    print(f"21 instances in {into} — {had} already there, {got} fetched and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
