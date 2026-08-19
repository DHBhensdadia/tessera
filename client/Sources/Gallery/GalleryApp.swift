import DesignSystem
import SwiftUI

/// Every component, in every state, in both schemes, on one screen.
///
/// This is the exit test of Phase 3.1 and the one part of it no test replaces. The suite
/// proves the system is complete, legible and consistent; whether it is *good* is a
/// judgement, and this is the thing you make it on.
///
/// Both schemes are shown side by side rather than behind a toggle, because a design is
/// reviewed by comparison. Flipping between them from memory is how a dark mode ships with
/// one panel a shade wrong.
@main
struct GalleryApp: App {
    var body: some Scene {
        WindowGroup("Tessera Design System \(designSystemVersion)") {
            GalleryWindow()
        }
        .defaultSize(width: 1180, height: 820)
    }
}

struct GalleryWindow: View {
    @State private var reduceTransparency = false
    @State private var increaseContrast = false
    @State private var reduceMotion = false
    /// Overridable so the macOS 14–15 appearance can be reviewed on a macOS 26 machine.
    /// Without this the fallback path could only be seen by finding an old Mac.
    @State private var liquidGlass = Appearance.systemSupportsLiquidGlass

    private func appearance(_ scheme: Appearance.Scheme) -> Appearance {
        var value = Appearance(
            scheme: scheme,
            reduceTransparency: reduceTransparency,
            increaseContrast: increaseContrast,
            reduceMotion: reduceMotion
        )
        value.supportsLiquidGlass = liquidGlass
        return value
    }

    var body: some View {
        VStack(spacing: 0) {
            settings
            Divider()
            HStack(spacing: 0) {
                ForEach(Appearance.Scheme.allCases, id: \.self) { scheme in
                    specimens(appearance(scheme))
                    if scheme == .light { Divider() }
                }
            }
        }
        .frame(minWidth: 900, minHeight: 600)
    }

    private var settings: some View {
        HStack(spacing: Spacing.section.points) {
            Toggle("Reduce Transparency", isOn: $reduceTransparency)
            Toggle("Increase Contrast", isOn: $increaseContrast)
            Toggle("Reduce Motion", isOn: $reduceMotion)
            Toggle("Liquid Glass", isOn: $liquidGlass)
            Spacer()
            Text(fillDescription)
                .font(Typography.caption.font)
                .foregroundStyle(.secondary)
        }
        .toggleStyle(.checkbox)
        .padding(Spacing.regular.points)
    }

    /// States what the chrome will actually be drawn with, so the window is not just a
    /// picture — it says which branch produced it.
    private var fillDescription: String {
        switch appearance(.light).fill(for: .chrome) {
        case .solid: "chrome: solid"
        case .systemMaterial: "chrome: ultraThinMaterial (macOS 14–15)"
        case .liquidGlass: "chrome: Liquid Glass (macOS 26)"
        }
    }

    private func specimens(_ appearance: Appearance) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.section.points) {
                Text(appearance.scheme.rawValue.capitalized)
                    .font(Typography.title.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))

                buttons(appearance)
                fields(appearance)
                rowsAndBadges(appearance)
                surfaces(appearance)
                emptyState(appearance)
                palette(appearance)
            }
            .padding(Spacing.section.points)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(appearance.swiftUI(SurfaceRole.base))
    }

    private func section(_ title: String, _ appearance: Appearance) -> some View {
        Text(title)
            .font(Typography.heading.font)
            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
    }

    private func buttons(_ appearance: Appearance) -> some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            section("Buttons — every emphasis, every state", appearance)
            ForEach(Emphasis.allCases, id: \.self) { emphasis in
                HStack(spacing: Spacing.snug.points) {
                    ForEach(ControlState.allCases, id: \.self) { state in
                        ActionButton(emphasis: emphasis, state: state, appearance: appearance) {
                            Text(state.rawValue)
                        }
                    }
                }
            }
        }
    }

    private func fields(_ appearance: Appearance) -> some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            section("Fields", appearance)
            HStack(alignment: .top, spacing: Spacing.loose.points) {
                Field(label: "Room name", placeholder: "LH-201", value: .constant("LH-201"), appearance: appearance)
                Field(label: "Focused", value: .constant("Block A"), state: .focused, appearance: appearance)
                Field(label: "Disabled", value: .constant(""), state: .disabled, appearance: appearance)
                Field(
                    label: "Seats",
                    value: .constant("forty"),
                    problem: "That is not a number of seats.",
                    appearance: appearance
                )
            }
        }
    }

    private func rowsAndBadges(_ appearance: Appearance) -> some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            section("Rows and badges", appearance)
            Card(title: "Rooms", appearance: appearance) {
                VStack(spacing: 0) {
                    Row("LH-201", detail: "Block A · projector", value: "60", appearance: appearance)
                    Divider()
                    Row("Computer Lab 1", detail: "Block C · 30 workstations", value: "70", appearance: appearance)
                    Divider()
                    Row("Chemistry Lab", detail: "Block B · 1 slot turnaround", value: "40", appearance: appearance)
                }
            }
            HStack(spacing: Spacing.snug.points) {
                ForEach(Badge.Tone.allCases, id: \.self) { tone in
                    Badge(tone.rawValue, tone: tone, appearance: appearance)
                }
            }
        }
    }

    private func surfaces(_ appearance: Appearance) -> some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            section("Surfaces — content is never glass", appearance)
            HStack(spacing: Spacing.loose.points) {
                ForEach(Material.allCases, id: \.self) { material in
                    // The label sits on a solid chip rather than on the specimen itself.
                    // Drawn straight onto glass it was washed out in light mode — which is
                    // the rule this gallery is demonstrating: glass has no fixed luminance,
                    // so text never goes directly on it.
                    VStack(spacing: Spacing.tight.points) {
                        Text(material.rawValue)
                            .font(Typography.caption.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.primary))
                        Text(label(for: appearance.fill(for: material)))
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    }
                    .padding(Spacing.snug.points)
                    .background(
                        appearance.swiftUI(SurfaceRole.raised),
                        in: RoundedRectangle(cornerRadius: Radius.control.points)
                    )
                    .padding(Spacing.loose.points)
                    .surface(material, appearance)
                }
            }
        }
    }

    private func label(for fill: Fill) -> String {
        switch fill {
        case .solid: "solid"
        case .systemMaterial: "material"
        case .liquidGlass: "glass"
        }
    }

    private func emptyState(_ appearance: Appearance) -> some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            section("Empty state", appearance)
            Card(appearance: appearance) {
                EmptyState(
                    symbol: "calendar.badge.plus",
                    title: "No terms yet",
                    explanation: "A term is a schedulable period. Everything a solver places belongs to exactly one.",
                    appearance: appearance
                )
                .frame(maxWidth: .infinity)
            }
        }
    }

    /// Every text role on every surface, with the measured ratio beside it — so the
    /// numbers the tests assert are visible rather than only asserted.
    private func palette(_ appearance: Appearance) -> some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            section("Contrast, measured", appearance)
            ForEach([SurfaceRole.base, .raised, .sunken], id: \.self) { surface in
                HStack(spacing: Spacing.regular.points) {
                    ForEach(TextRole.allCases.filter { $0 != .onAccent }, id: \.self) { role in
                        let ratio = appearance.colour(role).contrast(with: appearance.colour(surface))
                        VStack(spacing: 0) {
                            Text(role.rawValue)
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(role))
                            Text(String(format: "%.2f", ratio))
                                .font(Typography.data.font)
                                .foregroundStyle(appearance.swiftUI(role))
                        }
                    }
                }
                .padding(Spacing.snug.points)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(appearance.swiftUI(surface), in: RoundedRectangle(cornerRadius: Radius.control.points))
            }
        }
    }
}
