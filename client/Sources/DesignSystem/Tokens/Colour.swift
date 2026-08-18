import SwiftUI

/// A colour as numbers, so that questions about it can be answered by arithmetic.
///
/// SwiftUI's `Color` is opaque: you can draw with it and you cannot reliably ask it what
/// its components are without going through AppKit and a colour-space conversion that
/// varies by display. That makes "is this text legible on that background" impossible to
/// assert in a unit test — and legibility is the one property of a palette worth proving
/// rather than assuming.
///
/// So tokens are defined as extended-sRGB components in `0...1` and converted to `Color`
/// only at the moment of drawing. The whole of `contrast(with:)` is then plain
/// arithmetic that runs anywhere, including on a Linux CI runner with no display.
public struct Colour: Equatable, Sendable {
    public let red: Double
    public let green: Double
    public let blue: Double
    public let opacity: Double

    public init(red: Double, green: Double, blue: Double, opacity: Double = 1) {
        self.red = red
        self.green = green
        self.blue = blue
        self.opacity = opacity
    }

    /// From the notation designers actually write. `0xFBFAF8`, not three fractions.
    public init(hex: UInt32, opacity: Double = 1) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }

    public var swiftUI: Color {
        Color(.sRGB, red: red, green: green, blue: blue, opacity: opacity)
    }

    /// Relative luminance, per WCAG 2.1. Each channel is linearised out of the sRGB
    /// transfer function first, then weighted by how much the eye responds to it — which
    /// is why green counts for roughly seven times what blue does.
    public var relativeLuminance: Double {
        func linear(_ channel: Double) -> Double {
            channel <= 0.03928 ? channel / 12.92 : pow((channel + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)
    }

    /// The WCAG contrast ratio between two colours: `1` for identical, `21` for black on
    /// white. Order does not matter.
    ///
    /// Both colours are assumed opaque. A translucent foreground has no single ratio —
    /// it depends on what happens to be behind it — which is one more reason the tokens
    /// used for text are all fully opaque.
    public func contrast(with other: Colour) -> Double {
        let a = relativeLuminance
        let b = other.relativeLuminance
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)
    }
}
