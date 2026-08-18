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
public enum Typography: String, CaseIterable, Sendable {
    /// A window or sheet title.
    case title
    /// A section heading inside a pane.
    case heading
    /// Body copy, form labels, list rows — the default.
    case body
    /// Supporting detail: counts, timestamps, helper text under a field.
    case caption
    /// Slot times, room codes, anything that must line up in a column.
    case mono

    public var font: Font {
        switch self {
        case .title: .system(.title2, design: .default, weight: .semibold)
        case .heading: .system(.headline, design: .default, weight: .semibold)
        case .body: .system(.body)
        case .caption: .system(.caption)
        // Tabular figures, so a column of times does not shuffle sideways as the digits
        // change. This is the whole reason a monospaced role exists.
        case .mono: .system(.body, design: .monospaced).monospacedDigit()
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
        case .mono: 2
        case .caption: 3
        }
    }
}
