import Testing

@testable import DesignSystem

/// That the platform difference and the accessibility branch are both real.
///
/// `fill(for:)` is a pure function returning a value, which is what makes this testable
/// at all: the alternative — a view modifier reaching for a material inline — can only be
/// checked by looking at it on two operating systems.
struct MaterialTests {
    @Test func glassIsNeverUsedForContent() {
        // Apple's guidance for the 26 releases: Liquid Glass belongs to the functional
        // layer and never to content. Here that is a property of the role, so it holds on
        // every platform and under every setting rather than by review.
        for appearance in Appearance.all {
            var probe = appearance
            probe.supportsLiquidGlass = true
            if case .liquidGlass = probe.fill(for: .content) {
                Issue.record("content resolved to glass in \(appearance)")
            }
        }
        #expect(!Material.content.isFunctional)
    }

    @Test func chromeAndOverlayUseGlassWhereItExists() {
        var modern = Appearance()
        modern.supportsLiquidGlass = true

        #expect(modern.fill(for: .chrome) == .liquidGlass)
        #expect(modern.fill(for: .overlay) == .liquidGlass)
    }

    /// The macOS 14–15 path. Unreachable on the machine this runs on, which is exactly
    /// why platform support is part of the value rather than a `#available` inside the
    /// function — otherwise the branch every older user sees would be untested.
    @Test func olderSystemsFallBackToTheSystemMaterial() {
        var legacy = Appearance()
        legacy.supportsLiquidGlass = false

        #expect(legacy.fill(for: .chrome) == .systemMaterial)
        #expect(legacy.fill(for: .overlay) == .systemMaterial)
    }

    @Test func reduceTransparencyMakesEverySurfaceSolid() {
        for scheme in Appearance.Scheme.allCases {
            for supported in [true, false] {
                var appearance = Appearance(scheme: scheme, reduceTransparency: true)
                appearance.supportsLiquidGlass = supported

                for material in Material.allCases {
                    guard case .solid = appearance.fill(for: material) else {
                        Issue.record("\(material.rawValue) stayed translucent under Reduce Transparency")
                        continue
                    }
                }
            }
        }
    }

    /// Reduce Transparency outranks the platform. Getting this the other way round would
    /// mean the newest OS ignored the setting, which is the worst possible combination.
    @Test func reduceTransparencyOutranksLiquidGlass() {
        var appearance = Appearance(reduceTransparency: true)
        appearance.supportsLiquidGlass = true

        #expect(appearance.fill(for: .chrome) != .liquidGlass)
    }

    /// **Every promised pairing has an opaque background, and that is the whole point.**
    ///
    /// `Material` and `SurfaceRole` are different axes, which is easy to blur: a role is a
    /// colour, a material is how a plane is drawn. Glass has no fixed luminance — it
    /// refracts whatever is behind the window — so no ratio can be computed for text on
    /// it, and the promise therefore only ever covers opaque roles.
    ///
    /// The gallery is what made the consequence visible: labels drawn straight onto a
    /// glass specimen were washed out in light mode, and no test could have said so
    /// because no test had anything to measure. The rule that follows is structural rather
    /// than numeric — prose belongs on `.content`, which is never glass — and it is
    /// recorded here beside the assertion that keeps the numeric half honest.
    @Test func everyPromisedBackgroundIsOpaque() {
        for appearance in Appearance.colourRelevant {
            for pairing in Pairing.promised {
                #expect(
                    appearance.colour(pairing.background).opacity == 1,
                    "\(pairing.background.rawValue) is translucent, so its contrast is undefined"
                )
            }
        }
    }

    /// Content is the only material a component may put text on, because it is the only
    /// one that is always a flat colour.
    @Test func contentIsTheOnlyMaterialThatIsAlwaysSolid() {
        for appearance in Appearance.all {
            var probe = appearance
            probe.supportsLiquidGlass = true

            let alwaysSolid = Material.allCases.filter { material in
                if case .solid = probe.fill(for: material) { return true }
                return false
            }
            if !probe.reduceTransparency {
                #expect(alwaysSolid == [.content])
            }
        }
    }

    /// A solid fallback has to be a colour that exists in the current scheme, or the
    /// setting that makes the app *more* readable would make it less.
    @Test func theSolidFallbackComesFromTheScheme() {
        for scheme in Appearance.Scheme.allCases {
            let appearance = Appearance(scheme: scheme, reduceTransparency: true)
            for material in Material.allCases {
                guard case .solid(let colour) = appearance.fill(for: material) else { continue }
                #expect(colour == appearance.colour(material.opaqueRole))
            }
        }
    }
}

/// That no interactive control quietly omits a state.
///
/// "We forgot the disabled state" is the commonest hole in a design system and it is
/// invisible until somebody disables something.
struct ControlStateTests {
    @Test func everyStateIsAccountedFor() {
        #expect(ControlState.allCases.count == 5)
        #expect(ControlState.allCases.contains(.disabled))
        #expect(ControlState.allCases.contains(.focused))
    }

    @Test func onlyDisabledIsNotEnabled() {
        for state in ControlState.allCases {
            #expect(state.isEnabled == (state != .disabled))
        }
    }

    /// Every state must actually *look* different.
    ///
    /// The gap the gallery found and the suite did not. A primary button returned the
    /// accent for all five states and an outlined one used the same surface for normal and
    /// hover, so a filled control had no press feedback and an outlined one no hover.
    /// Every earlier test passed: the states existed, they were enumerated, and they were
    /// legible. None of them asked whether they differed.
    @Test(arguments: Emphasis.allCases)
    func everyStateIsVisuallyDistinct(_ emphasis: Emphasis) {
        let appearance = Appearance()
        let interactive: [ControlState] = [.normal, .hover, .pressed]

        let surfaces = interactive.map { state in
            appearance.colour(
                TokenButtonStyle(emphasis: emphasis, source: .pinned(state), appearance: appearance)
                    .backgroundRole(state)
            )
        }

        for (index, first) in surfaces.enumerated() {
            for (otherIndex, second) in surfaces.enumerated() where otherIndex > index {
                #expect(
                    first != second,
                    """
                    \(emphasis.rawValue): \(interactive[index].rawValue) and \
                    \(interactive[otherIndex].rawValue) are the same colour, so the state \
                    change is invisible.
                    """
                )
            }
        }
    }

    /// Every emphasis must resolve to a legible foreground on whatever it puts behind it.
    /// A destructive button whose red sits on the accent, say, would pass the palette
    /// tests and still be unreadable — because the pairing is chosen by the component,
    /// not by the palette.
    @Test(arguments: Appearance.colourRelevant)
    func everyButtonPairingIsLegible(_ appearance: Appearance) {
        for emphasis in Emphasis.allCases {
            for state in ControlState.allCases {
                let style = TokenButtonStyle(emphasis: emphasis, source: .pinned(state), appearance: appearance)
                let ratio = appearance.colour(style.foregroundRole)
                    .contrast(with: appearance.colour(style.backgroundRole(state)))
                #expect(
                    ratio >= 4.5,
                    "\(emphasis.rawValue)/\(state.rawValue) is \(String(format: "%.2f", ratio)):1 in \(appearance.scheme.rawValue)"
                )
            }
        }
    }
}

/// What part 2 added, and the properties that keep it from becoming a frosted rectangle.
struct GlassTests {
    /// The rule Apple states and this system encodes structurally: glass belongs to the
    /// functional layer. `.content` has no path to it, on any OS, with any setting.
    @Test func contentIsNeverGlassOnAnyPlatform() {
        for scheme in Appearance.Scheme.allCases {
            for supportsGlass in [true, false] {
                var appearance = Appearance(scheme: scheme)
                appearance.supportsLiquidGlass = supportsGlass
                #expect(
                    appearance.fill(for: .content) == .solid(appearance.colour(SurfaceRole.panel)),
                    "content resolved to something translucent"
                )
            }
        }
    }

    /// Reduce Transparency outranks the platform. The other way round would mean the
    /// newest OS was the one that ignored the setting.
    @Test func reduceTransparencyBeatsLiquidGlass() {
        var appearance = Appearance(scheme: .dark, reduceTransparency: true)
        appearance.supportsLiquidGlass = true
        for material in Material.allCases {
            #expect(
                appearance.fill(for: material) == .solid(appearance.colour(material.opaqueRole)),
                "\(material.rawValue) stayed translucent under Reduce Transparency"
            )
        }
    }

    /// Grain is texture, not tint. Above a few percent it stops being a material and
    /// starts being a grey wash over everything.
    @Test func grainIsBarelyThere() {
        #expect(Grain.opacity > 0, "no grain at all is the flat look it exists to break")
        #expect(Grain.opacity < 0.06, "grain this strong reads as dirt")
        #expect(Grain.tile != nil, "the texture failed to build")
    }

    /// A fixed seed, so two renders of the same view are identical. Noise that changes
    /// between frames shimmers, and a snapshot that changes for no reason is one nobody
    /// trusts.
    @Test func theGrainIsDeterministic() throws {
        let first = try #require(Grain.tile)
        let second = try #require(Grain.tile)
        #expect(first === second, "the tile is rebuilt per access")
    }
}

/// The shape decisions, which no contrast or colour test can see.

/// The shape decisions, which no contrast or colour test can see.
struct ControlShapeTests {
    /// Both light references make the one action a screen is for a capsule and leave the
    /// rest rectangular. Shape distinguishes the primary action where colour cannot — in
    /// monochrome, at a glance, or for someone who cannot separate a near-black fill from
    /// the surface behind it.
    @Test func onlyThePrimaryActionIsAPill() {
        for state in ControlState.allCases {
            let primary = TokenButtonStyle(emphasis: .primary, source: .pinned(state), appearance: Appearance())
            #expect(primary.radius == .pill, "the primary action is not a pill when \(state.rawValue)")

            for emphasis in [Emphasis.secondary, .destructive] {
                let other = TokenButtonStyle(emphasis: emphasis, source: .pinned(state), appearance: Appearance())
                #expect(other.radius == .control, "\(emphasis.rawValue) should not be a pill")
            }
        }
    }
}

/// A control's outline is a boundary, not a separator.
struct ControlBoundaryTests {
    /// `border` carries no contrast minimum because a hairline between two rows of one
    /// list is decoration. A button's edge is not: WCAG asks 3:1 for it, and drawing it
    /// with the separator colour makes the control look like text.
    @Test func outlinedControlsUseABoundaryThatMustBeVisible() {
        for emphasis in [Emphasis.secondary, .destructive] {
            let style = TokenButtonStyle(emphasis: emphasis, source: .pinned(.normal), appearance: Appearance())
            #expect(style.borderRole.minimumContrast != nil,
                    "\(emphasis.rawValue) is outlined with a role that promises no contrast")
        }
    }
}

/// That elevation stayed where 3.1c put it.
///
/// The defect this exists to prevent is not "a shadow that is too strong" — it is a
/// shadow appearing under content *at all*, which is how an interface starts grouping by
/// elevation and ends up looking like generated markup. None of the seventeen references
/// does it once.
///
/// A value test cannot see this, because the mistake is a view modifier rather than a

/// number. So it reads the source, the same way `NoLiteralsTests` does.
struct ElevationTests {
    /// `shadow(` appears exactly once in the whole client, inside `floating(_:)`.
    ///
    /// Scoped to a spelling rather than to a semantic because that is what makes it
    /// enforceable: there is one way to draw a shadow in SwiftUI, and one place allowed
    /// to use it.
    ///
    /// Matched **without** a leading dot. The first version of this looked for `.shadow(`
    /// and the sanctioned call was an implicit-self `shadow(` — so the guard would have
    /// been blind to exactly the spelling it was written to catch. Watching it fail is
    /// what surfaced that; a guard that had passed on the first run would have shipped.
    @Test func onlyTheFloatingModifierDrawsAShadow() throws {
        let permitted = "Surfaces/Material.swift"

        var offences: [String] = []
        for file in NoLiteralsTests.swiftFiles(under: "Sources") {
            let source = try String(contentsOf: file, encoding: .utf8)
            for (number, line) in source.split(separator: "\n", omittingEmptySubsequences: false).enumerated()
            where line.contains("shadow(") {
                if file.path.hasSuffix(permitted) { continue }
                offences.append("\(file.lastPathComponent):\(number + 1) — \(line.trimmingCharacters(in: .whitespaces))")
            }
        }
        #expect(offences.isEmpty, "content does not float:\n\(offences.joined(separator: "\n"))")
    }

    /// And that the one permitted use is still there.
    ///
    /// Without this, deleting `floating(_:)` outright would make the check above pass for
    /// the wrong reason — the same failure mode as a scan that finds no files.
    @Test func theFloatingModifierStillExists() throws {
        let file = NoLiteralsTests.packageRoot
            .appending(path: "Sources/DesignSystem/Surfaces/Material.swift")
        let source = try String(contentsOf: file, encoding: .utf8)
        #expect(source.contains("public func floating(_ elevation: Elevation)"))
        #expect(source.contains("self.shadow("), "the only sanctioned shadow has gone missing")
    }
}

/// That the sheen stays a surface treatment rather than becoming a style.
