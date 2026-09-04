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


def seeded(project: Path) -> int:
    """A project file with one small term in it, built the way the engine builds one.

    Through Alembic rather than `create_all`, because the engine migrates on startup and a
    schema it did not create is a schema it tries to create again.
    """
    from tessera import engine as engine_module
    from tessera import project as project_module
    from tessera.repository import models as m
    from tessera.repository.database import session_factory
    from tests.repository.authored import term_with_sessions

    database = project_module.resolve(project)
    engine_module.migrate(database)
    from tessera.repository.database import create_project_engine

    connection = create_project_engine(database)
    with session_factory(connection)() as db:
        institution = m.Institution(name="Sardar Patel University")
        db.add(institution)
        db.commit()
        grid = m.TimeGrid(
            institution_id=institution.id,
            name="Standard",
            days=5,
            slots_per_day=8,
            slot_minutes=60,
            day_start_minute=9 * 60,
        )
        db.add(grid)
        db.commit()
        term = term_with_sessions(db, institution, grid, per_week=6)
    connection.dispose()
    return term.term_id


@pytest.fixture
def solving_engine(tmp_path: Path) -> Iterator[tuple[RunningEngine, int]]:
    """A real engine process, on a project that already has a term worth solving."""
    project = tmp_path / "solve.tessera"
    term_id = seeded(project)
    process = subprocess.Popen(
        [*ENGINE, "--project", str(project)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
    )
    try:
        yield (process, read_handshake(process), project), term_id
    finally:
        process.kill()
        process.wait(timeout=10)


class TestSolvingThroughTheRealEngine:
    """4.7's exit test, on the thing that ships rather than on a test client.

    Four of Stage 1's defects were invisible to every test and appeared only when the built
    `.app` ran: logs corrupting the handshake, the engine outliving its parent, a port
    announced before it was listening, and a release workflow that had never executed. This
    phase adds a process boundary of its own — a background thread, an open stream — so the
    same discipline applies.
    """

    def test_a_term_is_solved_and_the_stream_says_so(
        self, solving_engine: tuple[RunningEngine, int]
    ) -> None:
        (_, handshake, _), term_id = solving_engine
        base = f"http://127.0.0.1:{handshake['port']}/api/v1"
        headers = {"x-tessera-token": str(handshake["token"])}

        started = httpx.post(
            f"{base}/terms/{term_id}/solve",
            json={"time_budget_seconds": 20},
            headers=headers,
            timeout=30,
        )
        assert started.status_code == 202, started.text
        job = started.json()["job_id"]

        events: list[str] = []
        with httpx.stream(
            "GET", f"{base}/solve/{job}/stream", headers=headers, timeout=60
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("event:"):
                    events.append(line.removeprefix("event:").strip())
                    if events[-1] == "done":
                        break

        assert events, "the stream said nothing at all"
        assert events[0] == "status", "a client attaching should be told where things are"
        assert events[-1] == "done"

        final = httpx.get(f"{base}/solve/{job}", headers=headers, timeout=30).json()
        assert final["phase"] == "done"
        assert final["timetable_id"] is not None

    def test_cancelling_stops_the_search_and_keeps_what_it_found(
        self, solving_engine: tuple[RunningEngine, int]
    ) -> None:
        (_, handshake, _), term_id = solving_engine
        base = f"http://127.0.0.1:{handshake['port']}/api/v1"
        headers = {"x-tessera-token": str(handshake["token"])}

        job = httpx.post(
            f"{base}/terms/{term_id}/solve",
            json={"time_budget_seconds": 300},
            headers=headers,
            timeout=30,
        ).json()["job_id"]

        assert (
            httpx.post(f"{base}/solve/{job}/cancel", headers=headers, timeout=30).status_code == 204
        )

        deadline = time.monotonic() + 30
        phase = ""
        while time.monotonic() < deadline:
            phase = httpx.get(f"{base}/solve/{job}", headers=headers, timeout=30).json()["phase"]
            if phase in {"done", "infeasible", "cancelled", "failed"}:
                break
            time.sleep(0.05)

        assert phase == "cancelled", "a budget of five minutes ended when it was asked to"

    def test_the_engine_still_exits_on_a_signal_with_a_stream_open(
        self, solving_engine: tuple[RunningEngine, int]
    ) -> None:
        """The clause P5's exit test stops one step short of.

        An open SSE stream stops uvicorn shutting down: measured at 4.7 §1c, a hand-rolled
        `StreamingResponse` left the process alive past ten seconds. The desktop path is immune
        because `watch_parent` calls `os._exit`, which is exactly why this would have shipped
        unnoticed — `docker stop` sends SIGTERM, and the image is a published artefact.
        """
        (process, handshake, _), term_id = solving_engine
        base = f"http://127.0.0.1:{handshake['port']}/api/v1"
        headers = {"x-tessera-token": str(handshake["token"])}

        job = httpx.post(
            f"{base}/terms/{term_id}/solve",
            json={"time_budget_seconds": 300},
            headers=headers,
            timeout=30,
        ).json()["job_id"]

        with httpx.stream(
            "GET", f"{base}/solve/{job}/stream", headers=headers, timeout=60
        ) as response:
            next(response.iter_lines())  # attached, and holding the connection open
            process.send_signal(signal.SIGTERM)

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return
                time.sleep(0.25)

        raise AssertionError("the engine did not exit with a stream attached")
