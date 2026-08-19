import SwiftUI

/// What a colour is *for*, never what it looks like.
///
/// `TextRole.secondary` rather than `warmGrey`. The names survive a rebrand, they read
/// correctly in both schemes, and — the practical part — they make the accessibility
/// branches expressible in one place instead of at every call site.
public enum TextRole: String, CaseIterable, Sendable {
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
///
/// Three values, not three heights. `raised` and `sunken` were named for a z-position
/// they no longer have — with elevation gone from content (3.1c D1), the only thing
/// separating one plane from another is its *value*, and the names now say so.
public enum SurfaceRole: String, CaseIterable, Sendable {
    /// The window itself.
    case base
    /// A pane or bounded object sitting on the window: a sidebar, a rail, a table.
    case panel
    /// A well — a field, or anything the eye should read as set into the surface rather
    /// than laid on top of it.
    case well
    /// The plane under the pointer.
    case hover
    /// The plane under whatever is currently chosen.
    ///
    /// Separate from `well` because they move in different directions. A well is *deeper*
    /// than the surface in both schemes; a selection has to **separate** from it, which
    /// means darker in light and lighter in dark. Drawing a selection with `well` looked
    /// right in light and inverted in dark, where the chosen row came out darker than
    /// everything around it.
    case selection
    /// A filled control — the one surface that is a colour rather than a neutral.
    case accent
    /// The same control under the pointer, and while being pressed. Separate roles rather
    /// than an opacity applied to `accent`, because a translucent control changes its
    /// contrast against whatever is behind it while its label stays put.
    case accentHover
    case accentPressed
}

/// Lines: separators, control outlines, the focus ring.
public enum LineRole: String, CaseIterable, Sendable {
    case border, borderStrong, focusRing
    /// The outline of a control the user must fix before going on.
    ///
    /// Separate from `borderStrong` because a field that failed validation was drawing a
    /// heavier *neutral* outline, which on screen reads as emphasis — the same emphasis
    /// focus uses — rather than as a fault. The message underneath was the only thing
    /// that carried the meaning, and a message is easy to look past.
    ///
    /// The outline is never the *only* signal: the explanation below the field says what
    /// is wrong in words, so nothing here depends on distinguishing red (WCAG 1.4.1).
    case critical

    /// A control's visual boundary must reach 3:1 against what is adjacent (WCAG 2.1
    /// "Non-text Contrast"). A hairline separator between two rows of the same list is
    /// decoration and is exempt — which is exactly why `border` and `borderStrong` are
    /// two roles rather than one with an opacity applied by eye.
    public var minimumContrast: Double? {
        switch self {
        case .border: nil
        case .borderStrong, .focusRing, .critical: 3.0
        }
    }
}
