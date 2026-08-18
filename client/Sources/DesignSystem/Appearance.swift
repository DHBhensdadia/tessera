import SwiftUI

/// Everything that decides what a role resolves to: the colour scheme and the three
/// accessibility settings that change more than a preference pane usually does.
///
/// Passing this around explicitly, rather than reading the environment inside each
/// component, is what makes the whole system testable without rendering anything. A test
/// can construct `Appearance(scheme: .dark, increaseContrast: true)` and ask what
/// `Text.secondary` becomes — no window, no display, no snapshot.
public struct Appearance: Equatable, Sendable {
    public enum Scheme: String, CaseIterable, Sendable { case light, dark }

    public var scheme: Scheme

    /// **Reduce Transparency.** Materials become solid. This is not a cosmetic
    /// preference: for some people translucency makes text genuinely unreadable, and
    /// macOS also turns it on automatically to save power in Low Power Mode.
    public var reduceTransparency: Bool

    /// **Increase Contrast.** Muted text darkens toward the primary colour and hairlines
    /// become real lines. Distinct from Reduce Transparency, and frequently confused
    /// with it.
    public var increaseContrast: Bool

    /// **Reduce Motion.** Animations become instant or cross-fade. Vestibular disorders
    /// are the reason; the setting is not about taste.
    public var reduceMotion: Bool

    /// Whether this platform can draw Liquid Glass.
    ///
    /// Part of the value rather than queried at the point of drawing, so a test can ask
    /// what *would* be rendered on either OS without running on both. Without it the
    /// macOS 14 branch is unreachable from a suite running on macOS 26 — which is to say
    /// untested on the only versions where it is used.
    public var supportsLiquidGlass: Bool

    public init(
        scheme: Scheme = .light,
        reduceTransparency: Bool = false,
        increaseContrast: Bool = false,
        reduceMotion: Bool = false,
        supportsLiquidGlass: Bool = Appearance.systemSupportsLiquidGlass
    ) {
        self.scheme = scheme
        self.reduceTransparency = reduceTransparency
        self.increaseContrast = increaseContrast
        self.reduceMotion = reduceMotion
        self.supportsLiquidGlass = supportsLiquidGlass
    }

    /// Whether the machine this is running on can draw Liquid Glass. The default for
    /// `supportsLiquidGlass`, which a test overrides to reach the other branch.
    ///
    /// Lives here rather than beside the material code because it is a fact about the
    /// appearance, and because a default has to be defined wherever the property is.
    public static var systemSupportsLiquidGlass: Bool {
        if #available(macOS 26.0, *) { true } else { false }
    }

    /// Every combination, for the gallery and for tests that must cover all of them.
    public static var all: [Appearance] {
        Scheme.allCases.flatMap { scheme in
            [false, true].flatMap { transparency in
                [false, true].flatMap { contrast in
                    [false, true].map { motion in
                        Appearance(
                            scheme: scheme,
                            reduceTransparency: transparency,
                            increaseContrast: contrast,
                            reduceMotion: motion
                        )
                    }
                }
            }
        }
    }

    /// The two that matter for colour. Motion and transparency do not change a colour,
    /// so a contrast sweep over all sixteen would be fourteen repetitions.
    public static var colourRelevant: [Appearance] {
        Scheme.allCases.flatMap { scheme in
            [false, true].map { Appearance(scheme: scheme, increaseContrast: $0) }
        }
    }
}

extension Appearance {
    public func colour(_ role: TextRole) -> Colour {
        switch (role, scheme) {
        case (.primary, .light): Palette.lightTextPrimary
        case (.primary, .dark): Palette.darkTextPrimary

        // Under Increase Contrast the muted roles stop being muted. Collapsing them to
        // the primary colour rather than nudging them is deliberate: the setting exists
        // for people who cannot read low-contrast text, and a slightly-less-grey grey
        // helps nobody.
        case (.secondary, .light): increaseContrast ? Palette.lightTextPrimary : Palette.lightTextSecondary
        case (.secondary, .dark): increaseContrast ? Palette.darkTextPrimary : Palette.darkTextSecondary
        case (.tertiary, .light): increaseContrast ? Palette.lightTextSecondary : Palette.lightTextTertiary
        case (.tertiary, .dark): increaseContrast ? Palette.darkTextSecondary : Palette.darkTextTertiary

        case (.onAccent, .light): Palette.onLightAccent
        case (.onAccent, .dark): Palette.onDarkAccent

        case (.positive, .light): Palette.lightPositive
        case (.positive, .dark): Palette.darkPositive
        case (.warning, .light): Palette.lightWarning
        case (.warning, .dark): Palette.darkWarning
        case (.critical, .light): Palette.lightCritical
        case (.critical, .dark): Palette.darkCritical
        case (.info, .light): Palette.lightInfo
        case (.info, .dark): Palette.darkInfo
        }
    }

    public func colour(_ role: SurfaceRole) -> Colour {
        switch (role, scheme) {
        case (.base, .light): Palette.lightBase
        case (.base, .dark): Palette.darkBase
        case (.raised, .light): Palette.lightRaised
        case (.raised, .dark): Palette.darkRaised
        case (.sunken, .light): Palette.lightSunken
        case (.sunken, .dark): Palette.darkSunken
        case (.accent, .light): Palette.lightAccent
        case (.accent, .dark): Palette.darkAccent
        case (.accentHover, .light): Palette.lightAccentHover
        case (.accentHover, .dark): Palette.darkAccentHover
        case (.accentPressed, .light): Palette.lightAccentPressed
        case (.accentPressed, .dark): Palette.darkAccentPressed
        }
    }

    public func colour(_ role: LineRole) -> Colour {
        switch (role, scheme) {
        // A hairline becomes a real line rather than a darker hairline: the point of the
        // setting is that the boundary can be seen at all.
        case (.border, .light): increaseContrast ? Palette.lightBorderStrong : Palette.lightBorder
        case (.border, .dark): increaseContrast ? Palette.darkBorderStrong : Palette.darkBorder
        case (.borderStrong, .light): Palette.lightBorderStrong
        case (.borderStrong, .dark): Palette.darkBorderStrong
        case (.focusRing, .light): Palette.lightAccent
        case (.focusRing, .dark): Palette.darkAccent
        }
    }

    public func swiftUI(_ role: TextRole) -> Color { colour(role).swiftUI }
    public func swiftUI(_ role: SurfaceRole) -> Color { colour(role).swiftUI }
    public func swiftUI(_ role: LineRole) -> Color { colour(role).swiftUI }
}

/// A pairing the design system **promises** is legible.
///
/// Stated as data rather than checked by eye, and rather than testing every combination
/// blindly — some combinations are nonsensical (`onAccent` on `base` is not a thing a
/// component should do) and a test that demanded they pass would push the palette around
/// for no benefit. This list is the actual promise, and the test iterates it.
public struct Pairing: Sendable {
    public let foreground: TextRole
    public let background: SurfaceRole

    public init(_ foreground: TextRole, on background: SurfaceRole) {
        self.foreground = foreground
        self.background = background
    }
}

extension Pairing {
    /// Every text-on-surface combination a component is allowed to use.
    public static let promised: [Pairing] = {
        let neutrals: [SurfaceRole] = [.base, .raised, .sunken]
        let onNeutral: [TextRole] = [.primary, .secondary, .tertiary, .positive, .warning, .critical, .info]
        let filled: [SurfaceRole] = [.accent, .accentHover, .accentPressed]
        return neutrals.flatMap { surface in onNeutral.map { Pairing($0, on: surface) } }
            + filled.map { Pairing(.onAccent, on: $0) }
    }()
}
