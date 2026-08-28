import Testing

@testable import DesignSystem

/// Where the two ways of numbering a week meet.
///
/// The engine stores unavailability as **week-absolute** slot indices (#6) — `day ×
/// slotsPerDay + slotOfDay`. A `TimeGrid` stores its breaks as **slot-of-day** indices,
/// because a lunch break recurs at the same time every day and storing the week-absolute
/// form would make "move lunch by half an hour" a rewrite of every day.
///
/// Both are integers, both index a week, and confusing them produces a grid that looks
/// plausible and blocks the wrong afternoon. `AvailabilityGrid.Week` is the one place they
/// meet, so it is the one place worth pinning down.
struct AvailabilityGridTests {
    /// Nine to five, hourly, with an hour of lunch at 13:00 — slot-of-day 4.
    private let week = AvailabilityGrid.Week(
        days: 5,
        slotsPerDay: 8,
        slotMinutes: 60,
        dayStartMinute: 9 * 60,
        breakSlots: [4]
    )

    @Test func aSlotIsItsDayAndItsPlaceInThatDay() {
        #expect(week.slot(day: 0, of: 0) == 0)
        #expect(week.slot(day: 0, of: 7) == 7)
        #expect(week.slot(day: 1, of: 0) == 8, "Tuesday starts where Monday ended")
        #expect(week.slot(day: 4, of: 7) == 39, "the last slot of a five-day week")
    }

    @Test func everySlotDecomposesBackToWhereItCameFrom() {
        for day in 0..<week.days {
            for index in 0..<week.slotsPerDay {
                let slot = week.slot(day: day, of: index)
                #expect(week.day(of: slot) == day)
                #expect(week.slotOfDay(slot) == index)
            }
        }
    }

    /// The distinction this file exists for: a break is one time of day on **every** day.
    @Test func aBreakRecursEveryDay() {
        for day in 0..<week.days {
            #expect(week.isBreak(week.slot(day: day, of: 4)), "lunch is lunch on day \(day)")
            #expect(!week.isBreak(week.slot(day: day, of: 3)))
            #expect(!week.isBreak(week.slot(day: day, of: 5)))
        }
        // Read as week-absolute, slot 4 is Monday 13:00 and slot 12 is Tuesday 13:00. If
        // `breakSlots` were treated as week-absolute, only the first would be a break —
        // which is the mistake, and it is invisible on a one-day grid.
        #expect(week.isBreak(4))
        #expect(week.isBreak(12))
    }

    @Test func timesReadFromTheStartOfTheDay() {
        #expect(week.label(forSlotOfDay: 0) == "09:00")
        #expect(week.label(forSlotOfDay: 4) == "13:00")
        #expect(week.label(forSlotOfDay: 7) == "16:00")
    }

    /// Half-hour slots and a start that is not on the hour, because "09:00, hourly" is the
    /// case that hides an integer-division mistake.
    @Test func labelsSurviveAnAwkwardGrid() {
        let awkward = AvailabilityGrid.Week(
            days: 5, slotsPerDay: 4, slotMinutes: 45, dayStartMinute: 8 * 60 + 20
        )
        #expect(awkward.label(forSlotOfDay: 0) == "08:20")
        #expect(awkward.label(forSlotOfDay: 1) == "09:05")
        #expect(awkward.label(forSlotOfDay: 2) == "09:50")
    }

    /// A grid can be asked for one day, and the arithmetic must not assume five.
    @Test func aSingleDayWeekIsStillAWeek() {
        let one = AvailabilityGrid.Week(days: 1, slotsPerDay: 3, slotMinutes: 60, dayStartMinute: 0)
        #expect(one.slot(day: 0, of: 2) == 2)
        #expect(one.day(of: 2) == 0)
    }

    /// Degenerate input is clamped rather than allowed to divide by zero: a week of zero
    /// days is not a rendering problem, it is a crash.
    @Test func nothingIsEverZero() {
        let empty = AvailabilityGrid.Week(days: 0, slotsPerDay: 0, slotMinutes: 0, dayStartMinute: 0)
        #expect(empty.days == 1)
        #expect(empty.slotsPerDay == 1)
        #expect(empty.slotMinutes == 1)
    }
}
