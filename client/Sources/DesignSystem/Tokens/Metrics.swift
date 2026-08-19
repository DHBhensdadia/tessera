import SwiftUI

/// Spacing, on a four-point grid.
///
/// Four rather than eight because macOS controls are dense — an eight-point minimum
/// makes a toolbar look like an iPad app. Every value in the application comes from here,
/// so "the gap between a label and its field" has one answer rather than one per view.
public enum Spacing: String, CaseIterable, Sendable {
    case hairline, tight, snug, regular, loose, section, page

    public var points: CGFloat {
        switch self {
        case .hairline: 2
        case .tight: 4
        case .snug: 8
        case .regular: 12
        case .loose: 16
        case .section: 24
        case .page: 32
        }
    }

    /// Ordered smallest to largest — asserted by a test, because a scale with a gap out
    /// of order is a scale people stop trusting and start bypassing.
    public var rank: Int { Spacing.allCases.firstIndex(of: self) ?? 0 }
}

/// Corner radii, named by what is being rounded rather than by size, so that changing how
/// round the application feels is one edit.
///
/// **Small inside the window, large at its edge.** Measured across the seventeen
/// references: rows, fields and controls sit between 4 and 10; the window itself sits
/// between 16 and 20. Not one *inline* radius in any of them reaches 14.
///
/// 3.1b set `card` to 14 so that a floating card would read as soft, which was the right
/// value for the wrong object — 3.1c removed the card. On a flat surface the same radius
/// reads as inflated rather than as considered, so it comes back down, and the name goes
/// with it: there are no cards, only containers.
public enum Radius: String, CaseIterable, Sendable {
    case control, container, sheet, pill

    public var points: CGFloat {
        switch self {
        case .control: 6
        case .container: 10
        // The window's own radius, and the only large one. Sheets adopt it because a sheet
        // is a window that arrived from the top.
        case .sheet: 18
        // Large enough that any realistic control height rounds to a capsule.
        case .pill: 999
        }
    }

    /// Ordered smallest to largest, `pill` excepted — it is a shape, not a step.
    public var rank: Int { Radius.allCases.firstIndex(of: self) ?? 0 }
}

/// That a thing is **floating above** something else. Nothing weaker than that.
///
/// This used to be a decoration scale with a `raised` step that every card inherited by
/// existing, and that step was the whole defect 3.1c exists to fix: grouping content by
/// elevation is the single most recognised signature of generated interface code, and it
/// is an idiom none of the seventeen references uses even once.
///
/// Four of them show a shadow. Every one is a window, a popover, a sheet, or — on the
/// kanban board, where every other card is flat — **the one card being dragged**. The
/// shadow is a claim about z-position, spent on the one element the claim is true of.
///
/// So the cases are named after the things that float. There is no case for content,
/// because content does not float, and `surface()` has no way to ask for one.
///
/// The values stay wide and faint, and opacity still climbs faster than blur: 3.1b's
/// first attempt spread the largest shadow so thin it read as *less* raised than the one
/// below it, which only rendering the two side by side revealed.
public enum Elevation: String, CaseIterable, Sendable {
    /// Everything inline. The default, and the only value content is allowed.
    case flat
    /// Popovers, menus, autocomplete — above the window, dismissed by looking away.
    case popover
    /// Sheets, dialogs, and the proxy that follows the pointer during a drag.
    case sheet

    public var radius: CGFloat {
        switch self {
        case .flat: 0
        case .popover: 36
        case .sheet: 64
        }
    }

    public var yOffset: CGFloat {
        switch self {
        case .flat: 0
        case .popover: 8
        case .sheet: 16
        }
    }

    public var opacity: Double {
        switch self {
        case .flat: 0
        case .popover: 0.14
        case .sheet: 0.24
        }
    }
}
