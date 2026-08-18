import SwiftUI

/// What a colour is *for*, never what it looks like.
///
/// `Text.secondary` rather than `warmGrey`. The names survive a rebrand, they read
/// correctly in both schemes, and — the practical part — they make the accessibility
/// branches expressible in one place instead of at every call site.
public enum Text: String, CaseIterable, Sendable {
    case primary, secondary, tertiary
    case onAccent
    case positive, warning, critical, info

    /// The contrast this role promises against any surface it is paired with.
    ///
    /// WCAG 2.1 asks 4.5:1 for body text and 3:1 for large text. Everything here is
    /// declared as body text: a "large text only" role would need every call site to
    /// honour that, and nothing enforces it, so the weaker promise would be a promise
    /// in name only.
    public var minimumContrast: Double { 4.5 }
}

/// The planes content sits on.
public enum Surface: String, CaseIterable, Sendable {
    /// The window itself.
    case base
    /// A card or panel lifted off the window.
    case raised
    /// A well or inset field, pushed into it.
    case sunken
    /// A filled control — the one surface that is a colour rather than a neutral.
    case accent
}

/// Lines: separators, control outlines, the focus ring.
public enum Line: String, CaseIterable, Sendable {
    case border, borderStrong, focusRing

    /// A control's visual boundary must reach 3:1 against what is adjacent (WCAG 2.1
    /// "Non-text Contrast"). A hairline separator between two rows of the same list is
    /// decoration and is exempt — which is exactly why `border` and `borderStrong` are
    /// two roles rather than one with an opacity applied by eye.
    public var minimumContrast: Double? {
        switch self {
        case .border: nil
        case .borderStrong, .focusRing: 3.0
        }
    }
}
