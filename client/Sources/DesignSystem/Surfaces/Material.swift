import SwiftUI

/// What a plane is *for*, which is what decides whether it may be glass.
///
/// Apple's guidance for the 26 releases is explicit: Liquid Glass belongs to the
/// **functional** layer — controls, navigation, transient surfaces — and never to the
/// content layer. Expressing that as *which roles exist* is a much better way to enforce
/// it than a code review, because `.content` simply has no path to glass.
public enum Material: String, CaseIterable, Sendable {
    /// Sidebar, toolbar, inspector — the frame around the work.
    case chrome
    /// Cards, panels, the timetable grid itself. **Never glass.**
    case content
    /// Sheets, popovers, menus — transient and above everything.
    case overlay

    /// Whether this role belongs to the functional layer.
    var isFunctional: Bool {
        switch self {
        case .chrome, .overlay: true
        case .content: false
        }
    }

    /// The neutral this role falls back to when translucency is off or unavailable.
    var opaqueRole: SurfaceRole {
        switch self {
        case .chrome: .sunken
        case .content: .raised
        case .overlay: .raised
        }
    }
}

/// What will actually be drawn — decided as data, so it can be asserted without a window.
///
/// The same trick the colour tokens use. A view modifier that reaches for a material
/// inline can only be checked by looking at it; a pure function returning a value can be
/// checked by a test on a machine with no display.
public enum Fill: Equatable, Sendable {
    /// A flat colour. What every role becomes under Reduce Transparency.
    case solid(Colour)
    /// `Material.ultraThin` — macOS 14 and 15.
    case systemMaterial
    /// Liquid Glass — macOS 26 and later.
    case liquidGlass
}

extension Appearance {
    /// What a role resolves to, given the platform and the settings.
    ///
    /// Reduce Transparency wins over everything. It is not a preference about taste: for
    /// some people translucency makes text unreadable, and macOS also turns it on by
    /// itself in Low Power Mode.
    public func fill(for material: Material) -> Fill {
        if reduceTransparency || !material.isFunctional {
            return .solid(colour(material.opaqueRole))
        }
        return supportsLiquidGlass ? .liquidGlass : .systemMaterial
    }
}

extension View {
    /// Draw a surface. The only sanctioned way to put a background behind anything.
    @ViewBuilder
    public func surface(
        _ material: Material,
        _ appearance: Appearance,
        radius: Radius = .card
    ) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius.points, style: .continuous)

        switch appearance.fill(for: material) {
        case .solid(let colour):
            background(colour.swiftUI, in: shape)
        case .systemMaterial:
            background(.ultraThinMaterial, in: shape)
        case .liquidGlass:
            if #available(macOS 26.0, *) {
                glassEffect(.regular, in: shape)
            } else {
                // Unreachable: `fill(for:)` only returns this when the platform supports
                // it. Present because the compiler cannot know that, and because a
                // `fatalError` in a view is a crash waiting for an OS upgrade.
                background(.ultraThinMaterial, in: shape)
            }
        }
    }
}
