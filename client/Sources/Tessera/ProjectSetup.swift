import Foundation

/// Everything a brand-new project needs before it is worth showing to anyone.
///
/// Collected in the welcome window's sheet and applied by the project window once its
/// engine is serving, because there is no database to write into until the engine has been
/// launched on a path. That ordering is forced by the architecture and it is the one place
/// this flow departs from P7 Act 2, which shows the sheet ending in a Save As.
///
/// The compensation is that nothing is created until the last step: cancel the save panel
/// and no directory, no database and no engine ever existed.
struct ProjectSetup: Codable, Hashable, Sendable {
    var institution: String = ""
    var grid = TimeGridSetup()
    var academicYear: String = ProjectSetup.defaultAcademicYear
    var termName: String = "Autumn"

    /// The academic year the current date falls in, in the form institutions write it.
    ///
    /// A year that runs July to June, so August 2026 is "2026–27" and February 2027 is
    /// still "2026–27". Guessing this correctly is a small thing that stops the first
    /// screen asking a question the application could have answered.
    static var defaultAcademicYear: String {
        let now = Calendar.current.dateComponents([.year, .month], from: .now)
        let year = (now.month ?? 1) >= 7 ? (now.year ?? 2026) : (now.year ?? 2026) - 1
        return "\(year)–\(String(format: "%02d", (year + 1) % 100))"
    }
}

/// The most consequential screen in the application, as a value.
///
/// P7: *"changing it later invalidates every assignment"*, which is why the grid is settled
/// before a project exists rather than in a settings pane afterwards.
struct TimeGridSetup: Codable, Hashable, Sendable {
    /// **How many** teaching days, counted from Monday — not *which*.
    ///
    /// The model stores a day count (`TimeGridCreate.days`, 1–7) because a `TimeGrid` is
    /// one repeating week addressed by integer slot index. P7's mock draws a checkbox per
    /// weekday, which implies Monday–Wednesday–Friday is expressible; it is not, and
    /// pretending otherwise in the interface would produce a grid that silently means
    /// something else. Recorded as a real divergence rather than papered over.
    var days: Int = 5
    var startMinute: Int = 9 * 60
    var endMinute: Int = 17 * 60
    var slotMinutes: Int = 30
    /// Protected slots, as minute ranges. Converted to slot indices on the way out, since
    /// that is what the grid stores and what the solver reads.
    var breaks: [BreakWindow] = [BreakWindow(name: "Lunch", start: 13 * 60, end: 14 * 60)]

    var slotsPerDay: Int { max(1, (endMinute - startMinute) / slotMinutes) }
    var slotsPerWeek: Int { slotsPerDay * days }

    /// Slot-of-day indices covered by a break.
    ///
    /// Clamped at **both** ends, and then checked for an empty range. The first version
    /// clamped the lower bound to zero and the upper bound to the day, which is not the
    /// same thing: a break starting after teaching ends gives a lower bound past the upper
    /// one, and `22..<16` is not an empty range in Swift, it is a crash. The test that
    /// found it was written for the ordinary case of a break hanging over the end of the
    /// day, and caught a fatal error instead.
    var breakSlots: [Int] {
        let day = 0...slotsPerDay
        let covered = breaks.flatMap { window -> [Int] in
            let first = ((window.start - startMinute) / slotMinutes).clamped(to: day)
            let last = ((window.end - startMinute + slotMinutes - 1) / slotMinutes).clamped(to: day)
            guard first < last else { return [] }
            return Array(first..<last)
        }
        return Array(Set(covered)).sorted()
    }

    /// What the user actually gets to timetable in, which is the number that matters and
    /// the one P7 insists on stating out loud.
    var usableSlotsPerDay: Int { slotsPerDay - breakSlots.count }
    var usableSlotsPerWeek: Int { usableSlotsPerDay * days }

    struct BreakWindow: Codable, Hashable, Identifiable, Sendable {
        var id = UUID()
        var name: String
        var start: Int
        var end: Int
    }
}

extension Int {
    /// Minutes since midnight, as a clock reading.
    var asClockTime: String { String(format: "%02d:%02d", self / 60, self % 60) }

    func clamped(to range: ClosedRange<Int>) -> Int {
        Swift.min(Swift.max(self, range.lowerBound), range.upperBound)
    }
}
