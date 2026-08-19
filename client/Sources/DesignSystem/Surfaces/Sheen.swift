import SwiftUI

/// A barely-perceptible directional wash across a large surface.
///
/// The problem this answers is specific. With elevation gone from content (3.1c D1), a
/// large pane is a single flat colour edge to edge, and a flat colour over 800 points
/// reads as *unrendered* rather than as calm — the eye is fairly good at telling a
/// deliberate plane from an empty one, and it uses the fact that real surfaces are never
/// evenly lit.
///
/// Two references solve it the same way: a very slight brightening across one diagonal,
/// far too faint to name as a gradient when you look at it, quite visible when it is
/// removed. That is the effect worth having, and it is **not** the same thing as the
/// decorative gradient that is itself a generated-interface tell — the difference is
/// amplitude, and the amplitude here is 2.5%.
///
/// **Opt-in, and off by default.** A wash applied to everything is a texture, and a
/// texture applied to everything is a style rather than a surface treatment. It is for
/// the window-sized planes: a sidebar, a content pane, a sheet. Never a row, never a
/// control.
public enum Sheen {
    /// Peak lightening at the bright corner. Deliberately below the threshold at which a
    /// screenshot compressor would keep it — if it survives JPEG it is too strong.
    public static let amplitude: Double = 0.025

    /// Where the light comes from. Top-leading in both schemes, because a surface lit
    /// from below reads as uncanny and every reference lights from above.
    static let start = UnitPoint.topLeading
    static let end = UnitPoint.bottomTrailing
}

extension View {
    /// Wash a large plane so it reads as lit rather than as filled.
    ///
    /// White in both schemes. Darkening the far corner instead would work in light and
    /// disappear in dark, which is the same asymmetry that made drop shadows unusable
    /// for grouping — adding light works in both.
    func sheened(_ shape: some Shape, enabled: Bool = true) -> some View {
        overlay {
            if enabled {
                shape
                    .fill(
                        LinearGradient(
                            colors: [
                                .white.opacity(Sheen.amplitude),
                                .white.opacity(0),
                            ],
                            startPoint: Sheen.start,
                            endPoint: Sheen.end
                        )
                    )
                    .allowsHitTesting(false)
            }
        }
    }
}
