"""Asking a running solve to stop, and having it actually stop.

ADR-0008 says cancellation is *"a flag the solver checks"*. It was written in August, before
there was a solver to check one, and a flag on its own is not enough: the loop reads it
between rounds, and the one unrestricted attempt holds the thread for its whole slice — up to
the entire budget. Measured at 4.7 §1a, a thirty-second solve of `comp02` under the default
preferences reaches **no** round boundary at all, so a cancel would arrive thirty seconds
after it was asked for.

CP-SAT has the other half. `CpSolver.stop_search()` is safe to call from another thread and
takes about a quarter of a second to bite:

| asked to stop at | `solve()` returned |
|---|---|
| 0.50 s | 0.206 s later |
| 3.00 s | 0.267 s later |

Neither half is sufficient alone. `stop_search()` reaches inside a running solve and does
nothing between two of them — the wrapper it needs exists only while `solve()` is on the
stack — and the flag is the opposite. So this holds both, and `running()` is what keeps them
in step: a stop requested while nothing is solving still stops the *next* solve before it
starts searching.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ortools.sat.python import cp_model

__all__ = ["Stop"]


class Stop:
    """A cancellation somebody asked for, and the solver currently able to honour it.

    Shared between the thread running the solve and the thread that wants it to end, so
    every field is guarded. Nothing here blocks: `request()` returns as soon as CP-SAT has
    been told, and the search unwinds on its own thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested = False
        self._solver: cp_model.CpSolver | None = None

    @property
    def requested(self) -> bool:
        """Whether anybody has asked for this to stop. Read on every loop boundary."""
        with self._lock:
            return self._requested

    def request(self) -> None:
        """Ask the search to stop, from any thread. Idempotent."""
        with self._lock:
            self._requested = True
            solver = self._solver
        # Outside the lock: `stop_search` takes CP-SAT's own, and holding two locks in one
        # order here while `running` takes them in the other is how a deadlock is written.
        if solver is not None:
            solver.stop_search()

    @contextmanager
    def running(self, solver: cp_model.CpSolver) -> Iterator[bool]:
        """Make this the solver a stop reaches, and say whether it is already too late.

        **The bool is the exact half and `stop_search()` is the approximate one.** A request
        arriving while nothing is searching has nothing to interrupt — `CpSolver.stop_search()`
        reaches a wrapper that exists only for the duration of one `solve()` call, so calling
        it beforehand does nothing at all and returns silently having done nothing. That is
        not a hypothetical: a cancel landing while the model is still being built in Python is
        the ordinary case at department scale, where construction is 2.15 s. So the caller
        asks, and skips the solve rather than starting one it has already been told to
        abandon.

        What is left is a window of a few microseconds: between this yielding `False` and
        CP-SAT creating the wrapper inside `solve()`, a request sets the flag and finds
        nothing to stop. The cost is one slice — bounded by `round_seconds` for a round and by
        `whole_seconds` for the unrestricted attempt — and then the loop reads the flag and
        ends. Closing it completely would need something that keeps asking, and a thread per
        cancellation is a poor trade for a window that narrow.
        """
        with self._lock:
            self._solver = solver
            already = self._requested
        try:
            yield already
        finally:
            with self._lock:
                self._solver = None
