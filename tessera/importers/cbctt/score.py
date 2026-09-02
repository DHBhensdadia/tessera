"""What a CB-CTT solution costs, read from the specification rather than from the solver.

**This is the oracle, and its independence is the point.** Phase 0.1 built a CP-SAT model of
this formulation and a checker of it, and the two agreed on the cost of all 21 instances —
zero mismatches. That agreement is evidence only because the two were separate readings: a
misreading would have had to appear identically in both. 4.1 carried the same discipline into
Tessera's own validator, and 4.5's D3 carries it here.

So nothing in this module may reason like the solver does. It imports no CP-SAT, which
`import-linter` enforces for the whole of `tessera.importers`, and it shares nothing with
`tessera.solver` beyond the parsed instance.

**The other half of the discipline, learned the same way.** Every run in the 0.1 sweep
reported feasible, and *a checker that always returned "no violations" would have produced
identical output* — every result worthless while looking perfect. A checker is verified by
being shown to fail, one rule at a time, which is what `tests/importers/cbctt/test_score.py`
does and why it exists in the same commit as this file.

The formulation is **UD2**, the one the `.ctt` files and the published results use, from the
competition's technical report (Di Gaspero, McCollum and Schaerf, §3). Two of its four soft
costs are counted in a way a paraphrase gets wrong, so they are spelled out here:

* **Compactness is per lecture, not per gap.** A curriculum taught at periods 1 and 3 of a day
  has *two* isolated lectures, not one gap. Tessera's own `MINIMISE_GROUP_GAPS` counts idle
  hours between the first and last, which is a different number on the same timetable; the two
  are not interchangeable and this module does not use one for the other.
* **Room stability is per course, not per lecture.** A course taught in three rooms costs two,
  however many lectures it has.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from tessera.importers.cbctt.format import Course, Instance
from tessera.importers.cbctt.solution import Placement

#: The four hard rules, named as the report names them. A solution breaking any is invalid
#: rather than expensive, and the competition does not score it at all.
RULES = ("Lectures", "Conflicts", "RoomOccupancy", "Availability")

# The weights are part of the formulation, not preferences, so they are constants here rather
# than arguments. Making them configurable would invite tuning them, and a benchmark whose
# objective can be tuned is not measuring anything anybody else can compare against.
CAPACITY_PENALTY = 1
"""Per student above the room's capacity, per lecture."""

WORKING_DAY_PENALTY = 5
"""Per day below a course's declared minimum."""

ISOLATED_LECTURE_PENALTY = 2
"""Per lecture with no adjacent lecture of the same curriculum on the same day."""

EXTRA_ROOM_PENALTY = 1
"""Per room a course uses beyond the first."""


@dataclass(frozen=True, slots=True)
class Violation:
    """A hard rule broken, and enough detail to find it in the file."""

    rule: str
    detail: str


@dataclass(frozen=True, slots=True)
class Costs:
    """The four soft costs, kept apart.

    Decomposed rather than summed because 4.3's exit test is that a score can be compared term
    by term against another reading of it, and a single total can agree by accident — two
    errors of opposite sign in different components look exactly like no error at all.
    """

    room_capacity: int = 0
    minimum_working_days: int = 0
    curriculum_compactness: int = 0
    room_stability: int = 0

    @property
    def total(self) -> int:
        return (
            self.room_capacity
            + self.minimum_working_days
            + self.curriculum_compactness
            + self.room_stability
        )


@dataclass(frozen=True)
class Report:
    """What the checker found: whether it is a solution at all, and what it costs."""

    violations: tuple[Violation, ...]
    costs: Costs

    @property
    def feasible(self) -> bool:
        return not self.violations

    @property
    def penalty(self) -> int:
        """The published metric. Meaningful only when `feasible`."""
        return self.costs.total

    @property
    def rules_broken(self) -> frozenset[str]:
        return frozenset(violation.rule for violation in self.violations)


def check(instance: Instance, placements: tuple[Placement, ...]) -> Report:
    """Score a solution against the instance it claims to solve.

    The soft costs are computed whatever the hard rules say. That is deliberate: a mutation
    test needs to see a cost move without a violation appearing, and an invalid solution whose
    costs are refused would make half of them unwritable. `feasible` is what says whether the
    penalty means anything.

    Placements naming a course or room the instance does not have are counted as violations
    and then skipped by the arithmetic, so a garbled file produces a report rather than a
    traceback.
    """
    known_courses = {course.id: course for course in instance.courses}
    capacities = {room.id: room.capacity for room in instance.rooms}

    violations = (
        *_lectures(instance, placements, known_courses),
        *_conflicts(instance, placements, known_courses),
        *_room_occupancy(placements, capacities),
        *_availability(instance, placements),
    )
    real = tuple(p for p in placements if p.course in known_courses)
    return Report(
        violations=violations,
        costs=Costs(
            room_capacity=sum(_over_capacity(real, known_courses, capacities).values())
            * CAPACITY_PENALTY,
            minimum_working_days=sum(_days_short(instance, real).values()) * WORKING_DAY_PENALTY,
            curriculum_compactness=len(_isolated(instance, real)) * ISOLATED_LECTURE_PENALTY,
            room_stability=sum(_extra_rooms(real).values()) * EXTRA_ROOM_PENALTY,
        ),
    )


def _lectures(
    instance: Instance,
    placements: tuple[Placement, ...],
    known_courses: dict[str, Course],
) -> list[Violation]:
    """Every lecture placed once, inside the timetable, and never twice in one period."""
    found: list[Violation] = []
    counted: defaultdict[str, int] = defaultdict(int)
    seen: defaultdict[tuple[str, int, int], int] = defaultdict(int)

    for placement in placements:
        if placement.course not in known_courses:
            found.append(
                Violation("Lectures", f"{placement.course!r} is not a course in this instance")
            )
            continue
        if not 0 <= placement.day < instance.days:
            found.append(
                Violation(
                    "Lectures",
                    f"{placement.course} is on day {placement.day}, "
                    f"outside the {instance.days}-day week",
                )
            )
            continue
        if not 0 <= placement.period < instance.periods_per_day:
            found.append(
                Violation(
                    "Lectures",
                    f"{placement.course} is at period {placement.period}, "
                    f"outside the {instance.periods_per_day} a day",
                )
            )
            continue
        counted[placement.course] += 1
        seen[placement.course, placement.day, placement.period] += 1

    for (course_id, day, period), times in sorted(seen.items()):
        if times > 1:
            found.append(
                Violation(
                    "Lectures", f"{course_id} is taught {times} times at day {day} period {period}"
                )
            )

    for course in instance.courses:
        placed = counted[course.id]
        if placed != course.lectures:
            found.append(
                Violation(
                    "Lectures",
                    f"{course.id} has {placed} lectures placed and needs {course.lectures}",
                )
            )
    return found


def _conflicts(
    instance: Instance,
    placements: tuple[Placement, ...],
    known_courses: dict[str, Course],
) -> list[Violation]:
    """Nothing a student or a teacher would have to be in two places for.

    Two lectures of the *same* course in one period trip this as well as `Lectures`, and that
    is the formulation's answer rather than double-counting: they do share a curriculum and a
    teacher. The mutation tests isolate the rules by constructing faults that trip one.
    """
    found: list[Violation] = []
    at: defaultdict[tuple[int, int], list[Placement]] = defaultdict(list)
    for placement in placements:
        if placement.course in known_courses:
            at[placement.day, placement.period].append(placement)

    curricula_of: defaultdict[str, list[str]] = defaultdict(list)
    for curriculum in instance.curricula:
        for course_id in curriculum.courses:
            curricula_of[course_id].append(curriculum.id)

    for (day, period), here in sorted(at.items()):
        by_curriculum: defaultdict[str, list[str]] = defaultdict(list)
        by_teacher: defaultdict[str, list[str]] = defaultdict(list)
        for placement in here:
            for curriculum_id in curricula_of[placement.course]:
                by_curriculum[curriculum_id].append(placement.course)
            by_teacher[instance.teacher_of(placement.course)].append(placement.course)

        for curriculum_id, courses in sorted(by_curriculum.items()):
            if len(courses) > 1:
                found.append(
                    Violation(
                        "Conflicts",
                        f"curriculum {curriculum_id} has {sorted(courses)} together "
                        f"at day {day} period {period}",
                    )
                )
        for teacher, courses in sorted(by_teacher.items()):
            if len(courses) > 1:
                found.append(
                    Violation(
                        "Conflicts",
                        f"{teacher} teaches {sorted(courses)} at once at day {day} period {period}",
                    )
                )
    return found


def _room_occupancy(
    placements: tuple[Placement, ...], capacities: dict[str, int]
) -> list[Violation]:
    """One lecture per room per period, and no lectures in rooms that do not exist."""
    found: list[Violation] = []
    used: defaultdict[tuple[str, int, int], list[str]] = defaultdict(list)

    for placement in placements:
        if placement.room not in capacities:
            found.append(
                Violation(
                    "RoomOccupancy",
                    f"{placement.course} is in {placement.room!r}, "
                    f"which is not a room in this instance",
                )
            )
            continue
        used[placement.room, placement.day, placement.period].append(placement.course)

    for (room_id, day, period), courses in sorted(used.items()):
        if len(courses) > 1:
            found.append(
                Violation(
                    "RoomOccupancy",
                    f"room {room_id} holds {sorted(courses)} at day {day} period {period}",
                )
            )
    return found


def _availability(instance: Instance, placements: tuple[Placement, ...]) -> list[Violation]:
    """No course in an hour it declared it cannot be taught in."""
    blocked = {(u.course, u.day, u.period) for u in instance.unavailable}
    return [
        Violation(
            "Availability",
            f"{p.course} is at day {p.day} period {p.period}, which it declares unavailable",
        )
        for p in sorted(placements)
        if (p.course, p.day, p.period) in blocked
    ]


def _over_capacity(
    placements: tuple[Placement, ...],
    known_courses: dict[str, Course],
    capacities: dict[str, int],
) -> dict[Placement, int]:
    """How many students would have to stand, per lecture."""
    return {
        placement: max(0, known_courses[placement.course].students - capacities[placement.room])
        for placement in placements
        if placement.room in capacities
    }


def _days_short(instance: Instance, placements: tuple[Placement, ...]) -> dict[str, int]:
    """How many days below its declared minimum each course is taught over."""
    days: defaultdict[str, set[int]] = defaultdict(set)
    for placement in placements:
        days[placement.course].add(placement.day)
    return {
        course.id: max(0, course.min_working_days - len(days[course.id]))
        for course in instance.courses
    }


def _isolated(instance: Instance, placements: tuple[Placement, ...]) -> list[tuple[str, int, int]]:
    """Every (curriculum, day, period) a curriculum holds with neither neighbour occupied.

    Per lecture and per curriculum: a course in two curricula is judged in both, and a course
    alone at period 1 with another of its curriculum at period 3 makes **two** isolated
    lectures rather than one gap. Adjacency does not cross a day boundary — the last period of
    Monday does not neighbour the first of Tuesday, because nobody experiences it that way.
    """
    where: defaultdict[str, set[tuple[int, int]]] = defaultdict(set)
    for placement in placements:
        where[placement.course].add((placement.day, placement.period))

    alone = []
    for curriculum in instance.curricula:
        occupied = {slot for course_id in curriculum.courses for slot in where[course_id]}
        for day, period in sorted(occupied):
            if (day, period - 1) not in occupied and (day, period + 1) not in occupied:
                alone.append((curriculum.id, day, period))
    return alone


def _extra_rooms(placements: tuple[Placement, ...]) -> dict[str, int]:
    """How many rooms beyond the first each course uses."""
    rooms: defaultdict[str, set[str]] = defaultdict(set)
    for placement in placements:
        rooms[placement.course].add(placement.room)
    return {course_id: max(0, len(used) - 1) for course_id, used in rooms.items()}


def blame(instance: Instance, placements: tuple[Placement, ...]) -> dict[Placement, int]:
    """What each lecture costs, for deciding which ones are worth moving.

    4.5's D2: the Fix-and-Optimize loop's `worst_first` strategy ranks sessions by an
    **independent** reading of the cost, never by the objective's own — otherwise one
    implementation gets to choose the neighbourhoods that flatter it. This is that reading for
    a CB-CTT run, and it is the same four counts `check` reports, attributed rather than
    summed.

    **The total is deliberately not the penalty.** Two of the four costs belong to a *course*
    rather than to any one of its lectures: a course taught on too few days, or in three rooms,
    is not a fault of the third lecture. Charging the whole of it to each lecture of that course
    ranks them all as worth moving, which is what a neighbourhood chooser needs; dividing it
    among them would round, and rounding a ranking to make it sum to a number nobody reads is
    the wrong trade. `check` remains the only thing that says what a solution costs.
    """
    known_courses = {course.id: course for course in instance.courses}
    capacities = {room.id: room.capacity for room in instance.rooms}
    real = tuple(p for p in placements if p.course in known_courses)

    cost: dict[Placement, int] = dict.fromkeys(real, 0)
    for placement, over in _over_capacity(real, known_courses, capacities).items():
        cost[placement] += over * CAPACITY_PENALTY

    of_course: defaultdict[str, list[Placement]] = defaultdict(list)
    for placement in real:
        of_course[placement.course].append(placement)

    for course_id, short in _days_short(instance, real).items():
        for placement in of_course[course_id]:
            cost[placement] += short * WORKING_DAY_PENALTY

    for course_id, extra in _extra_rooms(real).items():
        for placement in of_course[course_id]:
            cost[placement] += extra * EXTRA_ROOM_PENALTY

    members = {c.id: c.courses for c in instance.curricula}
    for curriculum_id, day, period in _isolated(instance, real):
        for placement in real:
            if (placement.day, placement.period) == (day, period) and placement.course in members[
                curriculum_id
            ]:
                cost[placement] += ISOLATED_LECTURE_PENALTY

    return cost
