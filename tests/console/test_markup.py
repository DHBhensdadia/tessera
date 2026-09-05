"""The contract between `watch.js` and the page it upgrades.

**Nothing in this project runs JavaScript**, and 4.8's D10 says so rather than leaving it to
be discovered: the script is verified by being run in a browser, and what is guarded here is
the thing that would silently break it. Rename an id in the template and the page stops
updating with no error anywhere — the server still renders, the stream still arrives, and the
numbers simply stand still. That is the failure this file exists to turn into a red test.

The contract is **read out of the script** rather than restated. A list of ids written here by
hand would be a second copy, and the first thing to drift would be the copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.console.test_solving import generate
from tests.repository.authored import Term

SCRIPT = Path(__file__).resolve().parents[2] / "tessera/templates/solve/watch.js"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


@pytest.fixture
def running(solving_console: TestClient, solvable: Term) -> str:
    """The watch page while its solve is still going, which is when the script is on it."""
    where = generate(solving_console, solvable.term_id, time_budget_seconds="30")
    page = str(solving_console.get(where).text)
    solving_console.post(f"{where}/stop")
    return page


class TestTheScriptIsRenderedSafely:
    def test_it_holds_no_template_expression(self, script: str) -> None:
        """An include is **not** autoescaped — `select_autoescape()` covers .html and .xml and
        not .js — so a variable written here would come out raw inside a `<script>` block
        while the same value in the page came out escaped. 4.8 §2.4 measured it both ways.

        It would also simply be substituted, which is how the first draft of the file's own
        warning comment was caught: it contained the delimiters it was warning about.
        """
        assert "{{" not in script
        assert "{%" not in script

    def test_it_travels_inside_the_page(self, running: str) -> None:
        """One response, and no `static/` directory to resolve, mount, bundle and smoke-test —
        `templates/` is already carried into the frozen build (#66)."""
        assert "<script>" in running
        assert "EventSource" in running


class TestEveryElementItWritesToExists:
    def test_the_ids_are_on_the_page(self, script: str, running: str) -> None:
        wanted = set(re.findall(r"""getElementById\(["'](.+?)["']\)""", script))

        assert wanted, "the scan found no ids — it is looking at the wrong thing"
        missing = sorted(one for one in wanted if f'id="{one}"' not in running)

        assert not missing, (
            f"`watch.js` writes into {missing} and the template renders no such element — "
            "the page would go quiet with no error anywhere"
        )

    def test_the_data_attributes_are_on_the_page(self, script: str, running: str) -> None:
        """Everything the script needs arrives this way rather than through the script's own
        text, because an attribute is autoescaped and an include is not."""
        wanted = set(re.findall(r"\.dataset\.(\w+)", script))

        assert wanted, "the scan found no data attributes — it is looking at the wrong thing"
        missing = sorted(
            one
            for one in wanted
            if f"data-{re.sub(r'(?<!^)(?=[A-Z])', '-', one).lower()}=" not in running
        )

        assert not missing, f"`watch.js` reads {missing} and the template supplies no such data-"


class TestThePhrasingItSelectsFrom:
    """The script swaps the heading and does not write it — the words stay in one place.

    Found by watching a real solve: a term that reached feasibility in under a second sat
    under the server's *"Looking for any valid timetable"* while the phase cell beneath it
    already read `optimising`. #305's family, one layer out.
    """

    def test_every_phase_the_server_words_is_rendered(self, running: str) -> None:
        from tessera.api.console.solving import PHASES

        missing = sorted(
            phase.value for phase in PHASES if f'data-phase="{phase.value}"' not in running
        )

        assert not missing, (
            f"`PHASES` words {missing} and the page renders no block for them — the heading "
            "would keep whatever the server said when the page loaded"
        )

    def test_the_words_come_from_the_server_and_not_the_script(self, script: str) -> None:
        """A copy here would drift from `console.solving.PHASES`, which is the drift #168 and
        #286 are both about."""
        from tessera.api.console.solving import PHASES

        for headline, _ in PHASES.values():
            assert headline not in script


class TestWhatTheStreamPromisesIsWhatTheScriptReads:
    def test_every_field_it_reads_is_on_the_wire(self, script: str) -> None:
        """The other half of the contract, and the half a browser cannot check for us: a field
        renamed in `SolveStatus` would leave the page showing `undefined`.

        Read from the schema rather than from a list, so adding a field is free and renaming
        one is loud.
        """
        from tessera.api.schemas import SolveStatus

        published = set(SolveStatus.model_fields)
        read = set(re.findall(r"status\.(\w+)", script))

        assert read, "the scan found no status fields — it is looking at the wrong thing"
        assert read <= published, (
            f"`watch.js` reads {sorted(read - published)}, which the stream does not send"
        )
