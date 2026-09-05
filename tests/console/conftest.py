"""A console addressed the way a browser addresses it, over a project on disk.

Two fixtures rather than one because the console has two kinds of page now. The sections that
only read and write rows are happy on the shared in-memory engine; anything that *solves* is
not, for the reason the root conftest gives — a solve commits from its own thread, and
`StaticPool` makes that the same transaction as the request's.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api import create_app


@pytest.fixture
def solving_console(project: Engine) -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=project, configure_logs=False), base_url="http://127.0.0.1"
    ) as client:
        yield client
