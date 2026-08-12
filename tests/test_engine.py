"""The sidecar: handshake, token, and dying with its parent.

These spawn the real engine as a subprocess rather than importing it, because the
behaviour under test only exists across a process boundary.

One honest limitation, recorded so nobody trusts these further than they deserve: the
orphan test below does **not** reproduce the regression that prompted it. That failure
appears only when the parent is the SwiftUI application, and could not be reproduced
with a Python parent, frozen engine or not. The real guard for it is
``packaging/smoke-test.sh``, which builds the app and kills it for real.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.slow

ENGINE = [sys.executable, "-m", "tessera.engine"]
REPO_ROOT = Path(__file__).resolve().parents[1]


def read_handshake(process: subprocess.Popen[bytes], timeout: float = 30.0) -> dict[str, object]:
    """First stdout line that parses as the handshake.

    Scans rather than trusting line one: the engine deliberately logs to stderr so that
    stdout stays clean, and this is what proves it.
    """
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "port" in payload:
            return dict(payload)
    raise AssertionError("engine produced no handshake")


#: What the engine fixture hands back: the process, its handshake, and the project file.
RunningEngine = tuple["subprocess.Popen[bytes]", dict[str, object], Path]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[RunningEngine]:
    project = tmp_path / "test.tessera"
    process = subprocess.Popen(
        [*ENGINE, "--project", str(project)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
    )
    try:
        handshake = read_handshake(process)
        yield process, handshake, project
    finally:
        process.kill()
        process.wait(timeout=10)


class TestHandshake:
    def test_it_announces_a_loopback_port_and_token(self, engine: RunningEngine) -> None:
        _, handshake, project = engine
        assert isinstance(handshake["port"], int)
        assert handshake["port"] > 0
        assert len(str(handshake["token"])) >= 32
        assert handshake["project"] == str(project)

    def test_stdout_carries_nothing_but_the_handshake(self, engine: RunningEngine) -> None:
        """Migration logs on stdout would corrupt the line the client parses.

        Alembic runs moments before the handshake is written, and its output went to
        stdout until logging was moved to stderr. The client then read a log line where
        it expected JSON and reported a broken engine.
        """
        _, handshake, _ = engine
        assert set(handshake) == {"port", "token", "pid", "project"}

    def test_it_serves_and_migrates_the_project(self, engine: RunningEngine) -> None:
        _, handshake, project = engine
        response = httpx.get(
            f"http://127.0.0.1:{handshake['port']}/health",
            headers={"x-tessera-token": str(handshake["token"])},
            timeout=10,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert project.exists(), "the project file should have been created and migrated"


class TestToken:
    def test_requests_without_it_are_refused(self, engine: RunningEngine) -> None:
        _, handshake, _ = engine
        response = httpx.get(f"http://127.0.0.1:{handshake['port']}/health", timeout=10)
        assert response.status_code == 401

    def test_a_wrong_token_is_refused(self, engine: RunningEngine) -> None:
        _, handshake, _ = engine
        response = httpx.get(
            f"http://127.0.0.1:{handshake['port']}/health",
            headers={"x-tessera-token": "not-the-token"},
            timeout=10,
        )
        assert response.status_code == 401

    def test_docs_stay_open(self, engine: RunningEngine) -> None:
        """The API shape is public knowledge; the project's data is not."""
        _, handshake, _ = engine
        assert (
            httpx.get(f"http://127.0.0.1:{handshake['port']}/docs", timeout=10).status_code == 200
        )


class TestOrphanPrevention:
    def test_the_engine_dies_with_its_parent(self, tmp_path: Path) -> None:
        """The watchdog exits when its parent is killed without cleanup.

        Genuine coverage of the mechanism, and **not** coverage of the regression that
        motivated it: a log call between the check and the exit made the engine outlive
        the SwiftUI application every time, yet this test passes with that call present.
        The failure needs a Swift parent. ``packaging/smoke-test.sh`` is what catches it.
        """
        launcher = tmp_path / "launcher.py"
        project = str(tmp_path / "orphan.tessera")
        launcher.write_text(
            "import json, os, signal, subprocess, sys\n"
            f"p = subprocess.Popen({ENGINE!r} + ['--project', {project!r}],\n"
            "                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,\n"
            f"                     cwd={str(REPO_ROOT)!r})\n"
            "while True:\n"
            "    line = p.stdout.readline()\n"
            "    if not line: raise SystemExit('no handshake')\n"
            "    try:\n"
            "        payload = json.loads(line)\n"
            "    except Exception:\n"
            "        continue\n"
            "    if 'port' in payload: break\n"
            "print(p.pid, flush=True)\n"
            # Die the way a force-quit does: no cleanup, no chance to terminate the child.
            "os.kill(os.getpid(), signal.SIGKILL)\n"
        )

        launched = subprocess.run(
            [sys.executable, str(launcher)], capture_output=True, timeout=60, check=False
        )
        child_pid = int(launched.stdout.decode().strip().splitlines()[0])

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                return  # exited, as it must
            time.sleep(0.5)

        with contextlib.suppress(ProcessLookupError):
            os.kill(child_pid, signal.SIGKILL)
        raise AssertionError(f"engine {child_pid} outlived its parent")
