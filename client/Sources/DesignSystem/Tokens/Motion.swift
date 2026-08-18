import SwiftUI

/// Durations and curves, named by what is moving.
///
/// The important property is not the numbers: it is that **every one of them collapses
/// when Reduce Motion is on**. Scattering `.animation(.easeInOut(duration: 0.2))` through
/// the views means the accessibility branch has to be remembered fifty times, and it will
/// not be. Asking the token for an animation means it is remembered zero times.
public enum Motion: String, CaseIterable, Sendable {
    /// A control reacting to a press or hover. Must feel immediate.
    case control
    /// A panel sliding, a sidebar opening.
    case panel
    /// A sheet or window presenting.
    case presentation

    public var duration: Double {
        switch self {
        case .control: 0.12
        case .panel: 0.22
        case .presentation: 0.32
        }
    }

    /// The animation to use, given the current settings.
    ///
    /// Reduce Motion does not mean "no feedback" — a control that changes with no
    /// transition at all reads as a glitch. It means no *movement*: the duration
    /// collapses to a cross-fade short enough that nothing appears to travel.
    public func animation(_ appearance: Appearance) -> Animation {
        appearance.reduceMotion
            ? .linear(duration: 0.01)
            : .easeOut(duration: duration)
    }
}
