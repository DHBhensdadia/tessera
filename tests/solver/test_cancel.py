"""Stopping a solve that is already running, and what comes back when one is stopped.

ADR-0008 says cancellation is *"a flag the solver checks"*, and `Stop` is two mechanisms because
that is half of one. They are tested in two places rather than one, and the split was arrived at
the hard way.

**The reach into a running search is tested on its own**, against a job shop CP-SAT answers
instantly and finishes slowly: left alone it burns 0.78 units of its own machine-independent work
and reports sixty-three improving solutions, and interrupted at the first of them it burns 0.001
and reports one. That is the claim #288 makes, measured in the unit #231 exists for, in a couple
of seconds.

**The wiring into `solve` is tested by what comes back**, never by how long it took. Two earlier
versions of these tests asserted seconds — how quickly a cancel is answered, and a ratio between
two runs — and both passed alone and failed inside the full suite under coverage. Coverage slows
Python and not C++, which moves *when a search is running* and therefore moves the thing being
timed. #244 says a test may not assert a wall-clock outcome; it turns out that includes asserting
one about a race.
"""

from __future__ import annotations

import random
import threading
import time

import pytest
from ortools.sat.python import cp_model

from tessera.domain.validation import Snapshot
from tessera.solver import Budget, Outcome, Progress, Solution, Stop, solve
from tessera.solver import model as build_model
from tessera.solver.search import _keep_going
from tests.solver.scored import department

#: Long enough that the one unrestricted attempt is still running when the cancel lands, and
#: short enough that a test which fails to cancel finishes rather than hanging.
WHILE_SEARCHING = Budget(seconds=10.0, whole_seconds=8.0)

#: When to ask, for the tests that are about **what comes back** rather than about how long it
#: took. Late enough that a first timetable exists on a small term and early enough that one does
#: not on a large one, which is the only property any of them depends on.
ASK_AT = 3.0


def cancel_after(stop: Stop, seconds: float) -> threading.Thread:
    """Ask for a stop from another thread, the way an HTTP request will."""

    def wait_then_ask() -> None:
        time.sleep(seconds)
        stop.request()

    thread = threading.Thread(target=wait_then_ask)
    thread.start()
    return thread


class TestTheHandleItself:
    def test_nobody_has_asked_until_somebody_asks(self) -> None:
        stop = Stop()

        assert stop.requested is False
        stop.request()
        assert stop.requested is True

    def test_asking_twice_is_asking_once(self) -> None:
        stop = Stop()
        stop.request()
        stop.request()

        assert stop.requested is True

    def test_a_stop_that_arrived_first_is_reported_rather_than_shouted_at_cpsat(self) -> None:
        """`stop_search()` before a solve does nothing, silently, and returns.

        Its wrapper is created inside `solve()` and cleared when that returns, so a request
        arriving while the model is still being built in Python — 2.15 s at department scale,
        the ordinary case — reaches nothing at all. **The first version of this test asserted
        that `stop_search()` had been called**, which it had, and the solve then ran to
        completion anyway; it passed with the defect present, which is the false guard
        WORKING-AGREEMENT ②b is about. What the caller needs is to be told, so it can decline
        to start a search it has already been asked to abandon.
        """
        stop = Stop()
        stop.request()

        with stop.running(cp_model.CpSolver()) as too_late:
            assert too_late is True

    def test_and_a_stop_that_has_not_arrived_is_not(self) -> None:
        stop = Stop()

        with stop.running(cp_model.CpSolver()) as too_late:
            assert too_late is False

    def test_a_request_reaches_the_solver_that_is_running_and_no_other(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stop = Stop()
        solver = cp_model.CpSolver()
        told: list[bool] = []
        monkeypatch.setattr(solver, "stop_search", lambda: told.append(True))

        with stop.running(solver):
            stop.request()
        assert told == [True]

        # Nothing is searching now, so there is nobody to tell — and telling a solver that
        # has already returned would reach into the *next* solve through the same object.
        stop.request()
        assert told == [True]

    def test_a_loop_boundary_is_not_crossed_once_a_stop_is_asked_for(self) -> None:
        stop = Stop()
        budget = Budget(seconds=300, rounds=9)

        assert _keep_going(budget, time.perf_counter(), 0, 5, stop) is True
        stop.request()
        assert _keep_going(budget, time.perf_counter(), 0, 5, stop) is False


def job_shop(jobs: int = 12, machines: int = 12, seed: int = 11) -> cp_model.CpModel:
    """A model CP-SAT answers instantly and finishes slowly.

    Deliberately not a timetable. What is being tested here is OR-Tools' own behaviour — that a
    `stop_search()` from another thread ends a search that is under way — and a term would drag
    the whole solver in to say something about one call. A job shop has the two properties the
    test needs and no others: a first solution immediately, and sixty-odd improvements after it.
    """
    rng = random.Random(seed)
    model = cp_model.CpModel()
    horizon = jobs * machines * 100
    ends: list[cp_model.IntVar] = []
    on_machine: dict[int, list[cp_model.IntervalVar]] = {m: [] for m in range(machines)}
    for job in range(jobs):
        order = list(range(machines))
        rng.shuffle(order)
        previous: cp_model.IntVar | None = None
        for machine in order:
            start = model.new_int_var(0, horizon, f"start[{job},{machine}]")
            end = model.new_int_var(0, horizon, f"end[{job},{machine}]")
            on_machine[machine].append(
                model.new_interval_var(start, rng.randint(10, 99), end, f"task[{job},{machine}]")
            )
            if previous is not None:
                model.add(start >= previous)
            previous = end
            ends.append(end)
    for tasks in on_machine.values():
        model.add_no_overlap(tasks)
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, ends)
    model.minimize(makespan)
    return model


class _AtTheFirstSolution(cp_model.CpSolverSolutionCallback):
    def __init__(self, found: threading.Event) -> None:
        super().__init__()
        self.found = found
        self.solutions = 0

    def on_solution_callback(self) -> None:
        self.solutions += 1
        self.found.set()


def searched(*, interrupted: bool) -> tuple[float, int]:
    """Run the job shop to its own conclusion, optionally stopping it at its first answer.

    Returns CP-SAT's machine-independent work and how many solutions it reported, so the
    comparison below is about the mechanism rather than about the afternoon (#231).
    """
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    stop = Stop()
    found = threading.Event()
    watcher = _AtTheFirstSolution(found)

    asker: threading.Thread | None = None
    if interrupted:

        def ask_once_there_is_something_to_keep() -> None:
            found.wait(60)
            stop.request()

        asker = threading.Thread(target=ask_once_there_is_something_to_keep)
        asker.start()

    with stop.running(solver):
        solver.solve(job_shop(), watcher)
    if asker is not None:
        asker.join()
    return solver.deterministic_time, watcher.solutions


class TestTheReachIntoARunningSearch:
    """#288's claim, on its own, in the unit CP-SAT measures itself in."""

    def test_a_search_left_alone_runs_to_its_own_end(self) -> None:
        work, solutions = searched(interrupted=False)

        assert solutions > 10, "this model is meant to keep finding better answers"
        assert work > 0.1, "and to spend real effort doing it"

    def test_and_one_asked_to_stop_from_another_thread_does_not(self) -> None:
        """The half of `Stop` a flag cannot be.

        The request is made from another thread, as it will be by a cancel route, and it is
        triggered by the search finding something rather than by a clock — so it lands inside
        `solver.solve()` on any machine and under coverage.
        """
        alone, _ = searched(interrupted=False)
        cut_short, solutions = searched(interrupted=True)

        assert cut_short < alone / 2, (
            f"the search did {cut_short:.3f} units of work after being asked to stop and "
            f"{alone:.3f} when left alone, which is not the difference the mechanism is for"
        )
        assert solutions >= 1, "and it kept the answer it had when it was asked"


class _AsksLate(Stop):
    """A stop that arrives at a chosen point in the loop rather than at a chosen time.

    Counts how often the loop has asked and requests itself once it has been asked enough,
    which puts the request in the same place on every machine and under coverage. `running()`
    reads the real flag rather than this, which is what makes the simulation honest: the loop
    sees a stop that was not there a moment ago, exactly as it would from another thread.
    """

    def __init__(self, after: int) -> None:
        super().__init__()
        self._reads = 0
        self._after = after

    @property
    def requested(self) -> bool:
        self._reads += 1
        answer = super().requested
        if self._reads >= self._after:
            self.request()
        return answer


def seconds_to_cancel(term: Snapshot, budget: Budget = WHILE_SEARCHING) -> tuple[float, Solution]:
    stop = Stop()
    began = time.perf_counter()
    asked = cancel_after(stop, ASK_AT)
    found = solve(term, budget, stop=stop)
    elapsed = time.perf_counter() - began
    asked.join()
    return elapsed, found


@pytest.mark.slow
class TestStoppingARunningSolve:
    def test_a_solve_asked_to_stop_before_it_starts_never_searches(self) -> None:
        """The exact half of the mechanism, on the case that made it necessary.

        A request landing while the model is still being built has nothing to interrupt, so the
        loop declines to start a search rather than starting one to abandon. Nothing was solved,
        so nothing was spent — and asking CP-SAT how much it did would raise rather than answer
        zero, which is #290.
        """
        stop = Stop()
        stop.request()

        found = solve(department(24, 6), Budget(seconds=30.0), stop=stop)

        assert found.outcome is Outcome.OUT_OF_TIME
        assert found.stopped is True
        assert found.work == 0.0

    def test_a_stop_between_the_first_timetable_and_optimising_it_builds_nothing_further(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The check in front of the whole model, and why it is in front rather than behind.

        Building that model is 2.15 s of Python at department scale and nothing can interrupt
        Python doing it, so a cancel checked one line later is answered two seconds late. What
        makes that assertable without timing it is **how many models get built**: the
        feasibility one, then the frozen one that prices the incumbent, and then — only if the
        search is still wanted — the whole one.

        The request is made from the feasibility progress event, the moment a valid timetable
        exists and before anything has priced it, so it lands in the same place every run.
        """
        builds = 0
        real = build_model.build

        def counted(*args, **kwargs):
            nonlocal builds
            builds += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(build_model, "build", counted)

        stop = Stop()

        def ask_as_soon_as_there_is_something_to_keep(event: Progress) -> None:
            if event.phase == "feasibility":
                stop.request()

        found = solve(
            department(24, 6),
            Budget(seconds=30.0),
            stop=stop,
            on_progress=ask_as_soon_as_there_is_something_to_keep,
        )

        assert found.outcome is Outcome.SOLVED
        assert found.stopped is True
        assert found.trajectory == ()
        assert builds == 2, (
            "a cancelled solve built a model it was never going to search — the check belongs "
            "in front of the build, not after it"
        )

    def test_a_request_landing_between_the_check_and_the_search_costs_nothing(self) -> None:
        """The window `_run`'s own guard covers, reproduced by counting rather than by racing.

        The loop reads the flag, finds it clear, builds a model, and only then reaches CP-SAT —
        and a request arriving in between would otherwise buy a whole solve nobody is waiting
        for. Reproducing that with a timer would be reproducing a race; `_AsksLate` arrives at a
        chosen *point* instead, which is the same place on every machine.
        """
        found = solve(department(24, 6), Budget(seconds=30.0), stop=_AsksLate(after=2))

        assert found.stopped is True
        assert found.trajectory == (), "a search that never ran is not a round"

    def test_a_stopped_solve_says_it_was_stopped(self) -> None:
        _, found = seconds_to_cancel(department(150, 12))

        assert found.stopped is True

    def test_and_keeps_the_timetable_it_had(self) -> None:
        """4.7 D4. Stopping is not discarding: whatever the search reached comes back.

        P7 draws `[ Stop ] [ Keep Result ]` and *"Use This Result is enabled from the first
        feasible solution"*. A stop that threw away forty seconds of improvement would make
        that button a trap.
        """
        term = department(150, 12)

        _, found = seconds_to_cancel(term)

        assert found.outcome is Outcome.SOLVED
        assert len(found.placements) == len(term.sessions)
        assert found.penalty >= 0

    def test_stopping_before_a_timetable_exists_says_so(self) -> None:
        """Nothing was found, and nothing is claimed. `Outcome` stays three-valued.

        Five hundred sessions take about five seconds to reach a first feasible timetable, so
        a cancel at a second and a half arrives while there is genuinely nothing to keep —
        which must not be reported as *impossible*, because nobody proved anything.
        """
        _, found = seconds_to_cancel(department(500, 40), Budget(seconds=30.0))

        assert found.outcome is Outcome.OUT_OF_TIME
        assert found.stopped is True
        assert found.placements == ()

    def test_a_solve_nobody_stops_says_so_too(self) -> None:
        found = solve(department(40, 6), Budget(seconds=5.0), stop=Stop())

        assert found.stopped is False
