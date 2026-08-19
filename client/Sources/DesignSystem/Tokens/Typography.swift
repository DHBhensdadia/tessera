import SwiftUI

/// The type scale, named by role.
///
/// Every style is built from a SwiftUI `Font.TextStyle` rather than from a point size,
/// which is what makes the whole application respond to the system text size without a
/// single extra line. A hardcoded `.system(size: 13)` looks identical on the machine it
/// was written on and ignores the setting that someone with low vision depends on.
///
/// The scale is deliberately short. A design system with fourteen text styles has, in
/// practice, no text styles: nobody can hold the distinctions, so people pick by eye and
/// the scale stops meaning anything.
///
/// `data` earns its place because this application is a timetable. Slot times, room codes,
/// capacities and headcounts all sit in columns, and a proportional font makes `09:30` and
/// `11:00` different widths — which is exactly the reference that sets an entire table in
/// monospace with right-aligned figures.
public enum Typography: String, CaseIterable, Sendable {
    /// A window or sheet title.
    case title
    /// A section heading inside a pane.
    case heading
    /// Body copy, form labels, list rows — the default.
    case body
    /// Supporting detail: counts, timestamps, helper text under a field.
    case caption
    /// **Figures, times, codes — anything that must line up in a column.**
    ///
    /// Named for the job rather than for the typeface, like every other role here. It is
    /// monospaced because that is what makes `09:30` and `11:00` the same width, not
    /// because monospace is a style.
    case data

    public var font: Font {
        switch self {
        case .title: .system(.title2, design: .default, weight: .semibold)
        case .heading: .system(.headline, design: .default, weight: .semibold)
        case .body: .system(.body)
        case .caption: .system(.caption)
        // Tabular figures, so a column of times does not shuffle sideways as the digits
        // change. This is the whole reason a monospaced role exists.
        case .data: .system(.body, design: .monospaced).monospacedDigit()
        }
    }

    /// Relative weight in the hierarchy, largest first. Used by a test to assert the
    /// scale is actually ordered — a "scale" whose heading is smaller than its body is a
    /// mistake that is surprisingly easy to make and surprisingly hard to see.
    public var rank: Int {
        switch self {
        case .title: 0
        case .heading: 1
        case .body: 2
        case .data: 2
        case .caption: 3
        }
    }
}
