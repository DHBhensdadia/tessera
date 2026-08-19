import Testing

@testable import DesignSystem

/// That the system is *complete* — every role has a value everywhere it is asked for.
///
/// These iterate `allCases` rather than listing roles, so adding a role without giving it
/// a value fails here rather than at the moment somebody uses it.
struct TokenTests {
    @Test(arguments: Appearance.colourRelevant)
    func everyTextRoleResolves(_ appearance: Appearance) {
        for role in TextRole.allCases {
            #expect(appearance.colour(role).opacity > 0, "\(role.rawValue) resolved to nothing")
        }
    }

    @Test(arguments: Appearance.colourRelevant)
    func everySurfaceAndLineResolves(_ appearance: Appearance) {
        for role in SurfaceRole.allCases {
            #expect(appearance.colour(role).opacity > 0)
        }
        for role in LineRole.allCases {
            #expect(appearance.colour(role).opacity > 0)
        }
    }

    /// The two schemes must actually differ. A dark mode that resolves to the light
    /// values is a dark mode nobody notices is broken until they use it at night.
    @Test func theSchemesAreNotTheSame() {
        let light = Appearance(scheme: .light)
        let dark = Appearance(scheme: .dark)

        for role in TextRole.allCases {
            #expect(light.colour(role) != dark.colour(role), "\(role.rawValue) is identical in both schemes")
        }
        for role in SurfaceRole.allCases {
            #expect(light.colour(role) != dark.colour(role), "\(role.rawValue) is identical in both schemes")
        }
    }

    @Test func theTypeScaleIsOrdered() {
        #expect(Typography.title.rank < Typography.heading.rank)
        #expect(Typography.heading.rank < Typography.body.rank)
        #expect(Typography.body.rank < Typography.caption.rank)
        // Monospace is body-sized: it is a different voice, not a different level.
        #expect(Typography.data.rank == Typography.body.rank)
    }

    @Test func spacingIsOrderedAndOnTheGrid() {
        let ordered = Spacing.allCases.sorted { $0.rank < $1.rank }
        for (smaller, larger) in zip(ordered, ordered.dropFirst()) {
            #expect(smaller.points < larger.points, "\(smaller.rawValue) is not smaller than \(larger.rawValue)")
        }
        // Every step lands on the four-point grid, except the deliberate 2pt hairline.
        for step in Spacing.allCases where step != .hairline {
            #expect(step.points.truncatingRemainder(dividingBy: 4) == 0, "\(step.rawValue) is off the grid")
        }
    }

    @Test func elevationIncreasesConsistently() {
        let ordered: [Elevation] = [.flat, .popover, .sheet]
        for (lower, higher) in zip(ordered, ordered.dropFirst()) {
            #expect(lower.radius < higher.radius)
            #expect(lower.opacity < higher.opacity)
            #expect(lower.yOffset < higher.yOffset)
        }
        #expect(Elevation.flat.opacity == 0, "a flat surface must cast no shadow at all")
    }

    /// Every elevation names something that genuinely floats above the window.
    ///
    /// Pinned as a list rather than left to review. The case this guards against is a
    /// future `raised` or `card` arriving because one view wanted a little separation —
    /// which is exactly how the scale it replaced came to exist, and how content ends up
    /// grouped by shadow again.

    /// Every elevation names something that genuinely floats above the window.
    ///
    /// Pinned as a list rather than left to review. The case this guards against is a
    /// future `raised` or `card` arriving because one view wanted a little separation —
    /// which is exactly how the scale it replaced came to exist, and how content ends up
    /// grouped by shadow again.
    @Test func everyElevationDescribesSomethingThatFloats() {
        #expect(Set(Elevation.allCases.map(\.rawValue)) == ["flat", "popover", "sheet"])
    }
}

/// That the accessibility settings are *branches*, not decoration.
///
/// Each of these asserts the resolved value actually changes. It is the only honest way
/// to test an accessibility setting without rendering: the claim is not "it looks right",
/// it is "something different comes out".
struct AccessibilityTests {
    @Test func increaseContrastChangesTheMutedText() {
        for scheme in Appearance.Scheme.allCases {
            let normal = Appearance(scheme: scheme)
            let increased = Appearance(scheme: scheme, increaseContrast: true)

            #expect(normal.colour(.secondary) != increased.colour(.secondary))
            #expect(normal.colour(.tertiary) != increased.colour(.tertiary))
            // Primary is already at full strength; changing it would be noise.
            #expect(normal.colour(.primary) == increased.colour(.primary))
        }
    }

    @Test func increaseContrastMakesHairlinesReal() {
        for scheme in Appearance.Scheme.allCases {
            let normal = Appearance(scheme: scheme)
            let increased = Appearance(scheme: scheme, increaseContrast: true)
            #expect(normal.colour(.border) != increased.colour(.border))
            #expect(increased.colour(.border) == increased.colour(.borderStrong))
        }
    }

    @Test func reduceMotionCollapsesEveryDuration() {
        let moving = Appearance(reduceMotion: false)
        let still = Appearance(reduceMotion: true)

        for motion in Motion.allCases {
            #expect(motion.animation(moving) != motion.animation(still), "\(motion.rawValue) ignores Reduce Motion")
        }
    }

    /// Not zero. A control that changes with no transition at all reads as a glitch;
    /// Reduce Motion means nothing should appear to *travel*, not that feedback vanishes.
    @Test func reduceMotionIsAShortFadeRatherThanNothing() {
        for motion in Motion.allCases {
            #expect(motion.duration > 0.05, "\(motion.rawValue) is too short to be seen at all")
        }
    }

    @Test func everyCombinationOfSettingsIsCovered() {
        // 2 schemes x 3 booleans
        #expect(Appearance.all.count == 16)
        #expect(Set(Appearance.all.map(\.scheme)).count == 2)
    }
}

/// That the palette has the character the references have, not merely legal contrast.
///
/// Every colour here would pass a contrast suite; a warm palette and a cool one of equal
/// luminance pass identically. So the property that distinguishes this palette from the
/// one it replaced needs a test of its own, or the next person adjusting a colour by eye
/// will drift it back without anything objecting.
struct PaletteCharacterTests {
    /// Light neutrals are **cool** — blue above red. R6 §2.3: every reference does this,
    /// and the earlier warm palette was the single clearest difference from them.
    @Test func theLightNeutralsAreCool() {
        let light = Appearance(scheme: .light)
        for role in [SurfaceRole.base, .panel, .well] {
            let c = light.colour(role)
            #expect(c.blue > c.red, "\(role.rawValue) is not cool: r\(c.red) b\(c.blue)")
        }
        for role in [TextRole.primary, .secondary, .tertiary] {
            let c = light.colour(role)
            #expect(c.blue >= c.red, "\(role.rawValue) is warm")
        }
    }

    /// Dark neutrals are **exactly neutral** — equal channels, as sampled from three
    /// separate references. A three-point lean is invisible in a swatch and quite visible
    /// across a window.
    @Test func theDarkNeutralsAreNeutral() {
        let dark = Appearance(scheme: .dark)
        for role in [SurfaceRole.base, .panel, .well] {
            let c = dark.colour(role)
            #expect(abs(c.red - c.green) < 0.008 && abs(c.green - c.blue) < 0.008,
                    "\(role.rawValue) is tinted: r\(c.red) g\(c.green) b\(c.blue)")
        }
    }

    /// The accent is a neutral, not a hue. Colour is reserved for meaning — a violated
    /// constraint, a published scenario — and an accent that competes with the status
    /// roles beside it spends the budget on chrome.
    @Test func theAccentIsNeutral() {
        for scheme in Appearance.Scheme.allCases {
            let c = Appearance(scheme: scheme).colour(SurfaceRole.accent)
            let spread = max(c.red, c.green, c.blue) - min(c.red, c.green, c.blue)
            #expect(spread < 0.08, "the \(scheme.rawValue) accent is a hue, not a neutral")
        }
    }

    /// Blue survives in exactly one place, and it is the one the platform expects.
    @Test func onlyTheFocusRingIsBlue() {
        for scheme in Appearance.Scheme.allCases {
            let ring = Appearance(scheme: scheme).colour(LineRole.focusRing)
            #expect(ring.blue > ring.red + 0.1, "the focus ring is not blue in \(scheme.rawValue)")
        }
    }

    /// The three neutral planes are genuinely three planes.
    ///
    /// New in 3.1c, and load-bearing in a way it was not before: until this phase a panel
    /// was separated from the window by a shadow, so the tone step underneath it could be
    /// almost anything. It is now the *only* thing separating them. A palette edit that
    /// collapsed two planes together used to cost a little flatness; it would now cost the
    /// structure of every screen.
    ///
    /// This asserts they are ordered and distinct, not that the step is large enough —
    /// "large enough" is judged by looking, and is recorded in the phase notes.
    @Test func theThreeNeutralPlanesAreDistinct() {
        for scheme in Appearance.Scheme.allCases {
            let appearance = Appearance(scheme: scheme)
            let planes = [SurfaceRole.base, .panel, .well].map { appearance.colour($0) }
            for (a, b) in [(planes[0], planes[1]), (planes[0], planes[2]), (planes[1], planes[2])] {
                #expect(a.contrast(with: b) > 1.0,
                        "two planes resolve to the same value in \(scheme.rawValue)")
            }
            // A panel is lighter than the window in light, and lighter in dark too: both
            // schemes add light to lift a plane. Darkening works in one and vanishes in
            // the other, which is the asymmetry that made shadows unusable for grouping.
            #expect(planes[1].relativeLuminance > planes[0].relativeLuminance,
                    "a panel does not read as a panel in \(scheme.rawValue)")
            #expect(planes[2].relativeLuminance < planes[0].relativeLuminance,
                    "a well does not read as set into the surface in \(scheme.rawValue)")
        }
    }

    /// Hover and selection separate from the plane behind them, in whichever direction
    /// that scheme allows, and selection separates further than hover.
    ///
    /// Stated as a direction rather than as values because the direction is the part that
    /// is easy to get wrong and impossible to see in a swatch. Drawing hover with the
    /// *pane* colour looked correct in dark — where a pane is lighter, and lighter is what
    /// hover wants — and in light produced a near-white card floating on the list. One
    /// role, two schemes, opposite meanings.

    /// Inline radii stay small and the window radius stays large. Stated as a relation
    /// rather than as four numbers, so it survives a deliberate re-tune of the values.
    @Test func inlineRadiiStaySmallerThanTheWindow() {
        #expect(Radius.control.points < Radius.container.points)
        #expect(Radius.container.points < Radius.sheet.points)
        #expect(Radius.container.points <= 12,
                "no inline radius in any reference reaches 14 — a container is not a card")
    }

    /// Radii pinned to the range the references actually use. Loosened in 3.1b when the
    /// unit was a floating card, tightened in 3.1c when the card was removed.
    @Test func shapesMatchTheReferenceLanguage() {
        #expect(Radius.control.points == 6)
        #expect(Radius.container.points == 10)
        #expect(Elevation.popover.opacity <= 0.15, "a wide shadow must also be faint")
    }

    /// The three neutral planes are genuinely three planes.
    ///
    /// New in 3.1c, and load-bearing in a way it was not before: until this phase a panel
    /// was separated from the window by a shadow, so the tone step underneath it could be
    /// almost anything. It is now the *only* thing separating them. A palette edit that
    /// collapsed two planes together used to cost a little flatness; it would now cost the
    /// structure of every screen.
    ///
    /// This asserts they are ordered and distinct, not that the step is large enough —
    /// "large enough" is judged by looking, and is recorded in the phase notes.

    /// Hover and selection separate from the plane behind them, in whichever direction
    /// that scheme allows, and selection separates further than hover.
    ///
    /// Stated as a direction rather than as values because the direction is the part that
    /// is easy to get wrong and impossible to see in a swatch. Drawing hover with the
    /// *pane* colour looked correct in dark — where a pane is lighter, and lighter is what
    /// hover wants — and in light produced a near-white card floating on the list. One
    /// role, two schemes, opposite meanings.
    @Test func hoverAndSelectionSeparateFromTheSurface() {
        for scheme in Appearance.Scheme.allCases {
            let appearance = Appearance(scheme: scheme)
            let base = appearance.colour(SurfaceRole.base)
            let hover = appearance.colour(SurfaceRole.hover)
            let selection = appearance.colour(SurfaceRole.selection)

            #expect(base.contrast(with: hover) > 1.0, "hover is invisible in \(scheme.rawValue)")
            #expect(base.contrast(with: selection) > base.contrast(with: hover),
                    "selection is no stronger than hover in \(scheme.rawValue)")

            // Light darkens, dark lightens. Both move away from the surface; there is only
            // one direction available in each.
            let darkens = scheme == .light
            #expect((hover.relativeLuminance < base.relativeLuminance) == darkens,
                    "hover moves the wrong way in \(scheme.rawValue)")
            #expect((selection.relativeLuminance < base.relativeLuminance) == darkens,
                    "selection moves the wrong way in \(scheme.rawValue)")
        }
    }

    /// A rule is visible in both schemes, and to a comparable degree.
    ///
    /// The device carrying every group boundary in the application, so it gets a floor and
    /// a symmetry check rather than being left to the eye. Written after the light rule
    /// was measured at 1.14:1 against the dark scheme's 1.28:1 — a difference invisible in
    /// a swatch and obvious in a window, where the light sidebar's rule simply was not
    /// there.
    ///
    /// The floor is deliberately below WCAG's 3:1: a separator between two rows of one
    /// list is decoration and is exempt (that is what `border` and `borderStrong` are two
    /// roles *for*). What it may not be is absent.
}
