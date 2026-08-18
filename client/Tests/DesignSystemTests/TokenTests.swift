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
        #expect(Typography.mono.rank == Typography.body.rank)
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
        let ordered: [Elevation] = [.flat, .raised, .floating, .modal]
        for (lower, higher) in zip(ordered, ordered.dropFirst()) {
            #expect(lower.radius < higher.radius)
            #expect(lower.opacity < higher.opacity)
            #expect(lower.yOffset < higher.yOffset)
        }
        #expect(Elevation.flat.opacity == 0, "a flat surface must cast no shadow at all")
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
