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

/// Corner radii, named by what is being rounded rather than by size, so that changing
/// how round the application feels is one edit.
public enum Radius: String, CaseIterable, Sendable {
    case control, card, sheet, pill

    public var points: CGFloat {
        switch self {
        case .control: 6
        case .card: 10
        case .sheet: 16
        // Large enough that any realistic control height rounds to a capsule.
        case .pill: 999
        }
    }
}

/// How far a surface sits off the one behind it.
///
/// Expressed as a shadow rather than a z-index because that is what the eye reads. The
/// values are restrained on purpose: heavy shadows are the fastest way to make a native
/// macOS application look like a web page.
public enum Elevation: String, CaseIterable, Sendable {
    case flat, raised, floating, modal

    public var radius: CGFloat {
        switch self {
        case .flat: 0
        case .raised: 3
        case .floating: 10
        case .modal: 28
        }
    }

    public var yOffset: CGFloat {
        switch self {
        case .flat: 0
        case .raised: 1
        case .floating: 4
        case .modal: 10
        }
    }

    public var opacity: Double {
        switch self {
        case .flat: 0
        case .raised: 0.10
        case .floating: 0.16
        case .modal: 0.24
        }
    }
}
