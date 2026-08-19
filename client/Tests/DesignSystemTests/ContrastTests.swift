import Testing

@testable import DesignSystem

/// Legibility, computed rather than judged.
///
/// This is the strongest objective guard a colour system can have, and it is the one most
/// design systems lack — the palette is chosen by eye, looks fine to the person choosing
/// it, and fails for someone else on a dimmer screen in a brighter room.
struct ContrastTests {
    /// The reference values are the ones WCAG defines, so a mistake in the formula shows
    /// up as a wrong answer here rather than as a palette that quietly passes.
    @Test func theFormulaAgreesWithItsDefinition() {
        let black = Colour(hex: 0x000000)
        let white = Colour(hex: 0xFFFFFF)

        #expect(abs(black.contrast(with: white) - 21) < 0.01)
        #expect(abs(white.contrast(with: white) - 1) < 0.01)
        // Order must not matter.
        #expect(black.contrast(with: white) == white.contrast(with: black))
        // A known middle value: #767676 on white is the classic 4.54:1 boundary case
        // that WCAG's own examples use.
        #expect(abs(Colour(hex: 0x767676).contrast(with: white) - 4.54) < 0.05)
    }

    @Test(arguments: Appearance.colourRelevant)
    func everyPromisedPairingIsLegible(_ appearance: Appearance) {
        for pairing in Pairing.promised {
            let foreground = appearance.colour(pairing.foreground)
            let background = appearance.colour(pairing.background)
            let ratio = foreground.contrast(with: background)

            #expect(
                ratio >= pairing.foreground.minimumContrast,
                """
                \(pairing.foreground.rawValue) on \(pairing.background.rawValue) \
                is \(String(format: "%.2f", ratio)):1 in \(appearance.scheme.rawValue)\
                \(appearance.increaseContrast ? " with increased contrast" : ""), \
                below the \(pairing.foreground.minimumContrast):1 this role promises.
                """
            )
        }
    }

    /// The case that catches an assumption rather than a typo. White on the *light*
    /// accent passes comfortably; white on the dark accent is 2.39:1, because the dark
    /// accent is a pale blue. Anyone "simplifying" `onAccent` to a single white value
    /// fails here.
    @Test func textOnTheAccentIsLegibleInBothSchemes() {
        for scheme in Appearance.Scheme.allCases {
            let appearance = Appearance(scheme: scheme)
            let ratio = appearance.colour(.onAccent).contrast(with: appearance.colour(.accent))
            #expect(ratio >= 4.5, "onAccent is \(ratio):1 in \(scheme.rawValue)")
        }
    }

    /// WCAG 2.1 "Non-text Contrast": a control's visual boundary needs 3:1 against what
    /// is next to it, or people cannot tell where the control is.
    @Test(arguments: Appearance.colourRelevant)
    func controlBoundariesAreVisible(_ appearance: Appearance) {
        for line in LineRole.allCases {
            guard let minimum = line.minimumContrast else { continue }
            for surface: SurfaceRole in [.base, .panel, .well] {
                let ratio = appearance.colour(line).contrast(with: appearance.colour(surface))
                #expect(
                    ratio >= minimum,
                    "\(line.rawValue) on \(surface.rawValue) is \(ratio):1 in \(appearance.scheme.rawValue)"
                )
            }
        }
    }

    /// Increase Contrast must never make anything *worse*. Easy to break by hand-picking
    /// a "stronger" colour that happens to have lower luminance separation.
    @Test func increasingContrastNeverReducesIt() {
        for scheme in Appearance.Scheme.allCases {
            let normal = Appearance(scheme: scheme)
            let increased = Appearance(scheme: scheme, increaseContrast: true)

            for pairing in Pairing.promised {
                let before = normal.colour(pairing.foreground)
                    .contrast(with: normal.colour(pairing.background))
                let after = increased.colour(pairing.foreground)
                    .contrast(with: increased.colour(pairing.background))
                #expect(
                    after >= before - 0.001,
                    "\(pairing.foreground.rawValue) on \(pairing.background.rawValue) fell from \(before) to \(after)"
                )
            }
        }
    }
}
