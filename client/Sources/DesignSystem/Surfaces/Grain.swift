import CoreGraphics
import SwiftUI

/// A faint noise texture laid over glass.
///
/// Three of the twelve references are photographic or halftoned rather than flat, and two
/// are *only* texture. That is not decoration: real materials have grain, and a perfectly
/// smooth gradient is what generated interfaces produce. A few percent of noise is one of
/// the cheapest ways to stop a translucent panel reading as synthetic.
///
/// The tile is built once and reused. Generating noise per frame would be a real cost for
/// something nobody can consciously see, and a *fixed* pattern is actually better: noise
/// that changes between frames shimmers.
enum Grain {
    /// Small enough to stay in cache, large enough that the repeat is not a visible grid.
    private static let size = 128

    static let tile: CGImage? = {
        let bytesPerPixel = 4
        var pixels = [UInt8](repeating: 0, count: size * size * bytesPerPixel)
        // A fixed seed, so the texture is identical on every launch and in every snapshot.
        // Without it two renders of the same view differ, and a picture that changes for
        // no reason is a picture nobody trusts.
        var seed: UInt64 = 0x5EED_1234_ABCD_0001
        for index in stride(from: 0, to: pixels.count, by: bytesPerPixel) {
            seed = seed &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
            let value = UInt8((seed >> 33) & 0xFF)
            pixels[index] = value
            pixels[index + 1] = value
            pixels[index + 2] = value
            pixels[index + 3] = 255
        }

        guard let provider = CGDataProvider(data: Data(pixels) as CFData) else { return nil }
        return CGImage(
            width: size,
            height: size,
            bitsPerComponent: 8,
            bitsPerPixel: 32,
            bytesPerRow: size * bytesPerPixel,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        )
    }()

    /// How much of it shows. Deliberately near the threshold of visibility: enough that a
    /// surface stops looking like flat paint, not enough that anyone notices texture.
    static let opacity: Double = 0.035
}

extension View {
    /// Lay the grain over a surface, clipped to its shape.
    func grained(_ shape: some Shape, enabled: Bool = true) -> some View {
        overlay {
            if enabled, let tile = Grain.tile {
                Image(decorative: tile, scale: 1)
                    .resizable(resizingMode: .tile)
                    .opacity(Grain.opacity)
                    // Overlay rather than normal, so the texture modulates what is beneath
                    // instead of greying it. A flat grey wash is exactly the synthetic look
                    // the grain exists to break.
                    .blendMode(.overlay)
                    .clipShape(shape)
                    .allowsHitTesting(false)
            }
        }
    }
}
