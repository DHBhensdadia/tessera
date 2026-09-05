"""Fixtures for the routes that start a real solve.

The project fixtures these build on live in the root `conftest`, because 4.8 gave the console
a second suite that solves and one definition beating two is the whole reason they were
written with a docstring rather than inline.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api import create_app


@pytest.fixture
def solving_client(project: Engine) -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=project, configure_logs=False), base_url="http://127.0.0.1"
    ) as client:
        yield client
