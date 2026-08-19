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
    ///
    /// Two things travel together, and they are the whole difference between "translucent"
    /// and "glass": the material itself, and a **hairline** so the plane has an edge
    /// against whatever is behind it. A frosted rectangle with no edge is the tutorial
    /// version.
    ///
    /// Grain rides on the translucent cases only. A solid fill has nothing to modulate.
    public func surface(
        _ material: Material,
        _ appearance: Appearance,
        radius: Radius = .card
    ) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius.points, style: .continuous)
        let fill = appearance.fill(for: material)

        return background {
            switch fill {
            case .solid(let colour):
                shape.fill(colour.swiftUI)
            case .systemMaterial:
                shape.fill(.ultraThinMaterial)
            case .liquidGlass:
                if #available(macOS 26.0, *) {
                    // `Color.clear` carries the effect: `glassEffect` styles a view, and
                    // the view it should style here is the shape itself rather than the
                    // content sitting on top of it.
                    Color.clear.glassEffect(.regular, in: shape)
                } else {
                    // Unreachable: `fill(for:)` returns this only where the platform has
                    // it. Present because the compiler cannot know that, and because a
                    // `fatalError` in a view is a crash waiting for an OS upgrade.
                    shape.fill(.ultraThinMaterial)
                }
            }
        }
        .grained(shape, enabled: fill != .solid(appearance.colour(material.opaqueRole)))
        .overlay(shape.strokeBorder(appearance.swiftUI(LineRole.border), lineWidth: 1))
    }
}
