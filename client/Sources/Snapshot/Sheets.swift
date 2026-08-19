import DesignSystem
import SwiftUI

/// One page of the design system per case, so a change can be reviewed as a diff of
/// pictures rather than as a diff of hex values.
enum Sheet: String, CaseIterable {
    case palette
    case shapes
    case components

    var width: CGFloat {
        switch self {
        case .palette, .shapes: 760
        case .components: 860
        }
    }

    @MainActor @ViewBuilder
    func view(_ appearance: Appearance) -> some View {
        switch self {
        case .palette: PaletteSheet(appearance: appearance)
        case .shapes: ShapeSheet(appearance: appearance)
        case .components: ComponentSheet(appearance: appearance)
        }
    }
}

/// Every component in every state, over a backdrop, so translucency has something to be
/// translucent against.
///
/// The backdrop is a gradient rather than a flat fill for one reason: a material laid over
/// a single colour looks identical to a tint of that colour, which is exactly how a
/// frosted rectangle passes for glass in a screenshot and fails on a desktop.
struct ComponentSheet: View {
    let appearance: Appearance

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.section.points) {
            Header("Components", appearance: appearance, note: appearance.scheme.rawValue)

            Caption("buttons — the primary action is a pill", appearance: appearance)
            VStack(alignment: .leading, spacing: Spacing.snug.points) {
                ForEach(Emphasis.allCases, id: \.self) { emphasis in
                    HStack(spacing: Spacing.snug.points) {
                        ForEach(ControlState.allCases, id: \.self) { state in
                            ActionButton(emphasis: emphasis, state: state, appearance: appearance) {
                                SwiftUI.Text(state.rawValue)
                            }
                        }
                    }
                }
            }

            Caption("rows — hover and selection are the same shape at two strengths", appearance: appearance)
            VStack(spacing: 0) {
                Row("LH-201", detail: "Block A · projector", value: "60", appearance: appearance)
                Row(
                    "Computer Lab 1",
                    detail: "Block C · 30 workstations",
                    value: "70",
                    isSelected: true,
                    appearance: appearance
                )
                Row(
                    "Chemistry Lab",
                    detail: "Block B · one slot turnaround",
                    value: "40",
                    state: .hover,
                    appearance: appearance
                )
            }

            Caption("a table is a grid of rules, not a box", appearance: appearance)
            DataTable(
                columns: [
                    Column("Room"),
                    Column("Location", width: 160),
                    Column("Seats", numeric: true, width: 56),
                ],
                rows: [
                    DataRow(id: "a", cells: ["LH-201", "Block A", "60"]),
                    DataRow(id: "b", cells: ["Computer Lab 1", "Block C", "70"], isSelected: true),
                    DataRow(id: "c", cells: ["Seminar Hall", "Block A", "120"]),
                ],
                appearance: appearance
            )

            Caption("badges", appearance: appearance)
            HStack(spacing: Spacing.snug.points) {
                ForEach(Badge.Tone.allCases, id: \.self) { tone in
                    Badge(tone.rawValue, tone: tone, appearance: appearance)
                }
            }

            Caption("surfaces — chrome and overlay are glass, content never is", appearance: appearance)
            HStack(spacing: Spacing.loose.points) {
                ForEach(Material.allCases, id: \.self) { material in
                    VStack(spacing: Spacing.snug.points) {
                        SwiftUI.Text(material.rawValue)
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.primary))
                            .padding(.horizontal, Spacing.snug.points)
                            .padding(.vertical, Spacing.tight.points)
                            .background(appearance.swiftUI(SurfaceRole.panel), in: Capsule())
                    }
                    .frame(width: 150, height: 88)
                    .surface(material, appearance, radius: .container)
                    // Only the overlay floats. Drawn here rather than described, because
                    // the specimen showing all three materials is exactly where "content
                    // does not cast a shadow" has to be visibly true.
                    .floating(material == .overlay ? .popover : .flat)
                }
            }
        }
        .padding(Spacing.page.points)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(backdrop)
    }

    /// Something for the glass to refract. A flat fill would prove nothing.
    ///
    /// Built from the public roles rather than from `Palette`, which is internal to the
    /// module — the boundary working as intended. Nothing outside the design system gets
    /// to name a colour.
    private var backdrop: some View {
        LinearGradient(
            colors: [
                appearance.swiftUI(SurfaceRole.well),
                appearance.swiftUI(SurfaceRole.panel),
                appearance.swiftUI(SurfaceRole.base),
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

/// Every colour role against every surface it is promised on, with the measured ratio
/// beside it — so the numbers the suite asserts are visible rather than only asserted.
struct PaletteSheet: View {
    let appearance: Appearance

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.section.points) {
            Header("Palette", appearance: appearance, note: appearance.scheme.rawValue)

            // Only the neutrals. `accent` and its states are *fills behind a label*, never a
            // page a paragraph sits on, so drawing body text on them would be showing a
            // pairing the design does not promise — and reporting a ratio for it.
            ForEach([SurfaceRole.base, .panel, .well], id: \.self) { surface in
                VStack(alignment: .leading, spacing: Spacing.snug.points) {
                    Caption(surface.rawValue, appearance: appearance)
                    VStack(spacing: 0) {
                        ForEach(textRoles, id: \.self) { role in
                            row(role, on: surface)
                        }
                    }
                    .background(appearance.swiftUI(surface), in: shape)
                    .overlay(shape.strokeBorder(appearance.swiftUI(LineRole.border), lineWidth: 1))
                }
            }

            accentStrip
        }
        .padding(Spacing.page.points)
        .background(appearance.swiftUI(SurfaceRole.base))
    }

    private var textRoles: [TextRole] { [.primary, .secondary, .tertiary, .positive, .warning, .critical, .info] }
    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: Radius.container.points, style: .continuous) }

    private func row(_ role: TextRole, on surface: SurfaceRole) -> some View {
        let ratio = appearance.colour(role).contrast(with: appearance.colour(surface))
        return HStack {
            Text("The quick brown fox — \(role.rawValue)")
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(role))
            Spacer()
            Text(String(format: "%.2f:1", ratio))
                .font(Typography.data.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        }
        .padding(.horizontal, Spacing.regular.points)
        .padding(.vertical, Spacing.snug.points)
    }

    private var accentStrip: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            Caption("accent — neutral, so colour is left for meaning", appearance: appearance)
            HStack(spacing: Spacing.regular.points) {
                ForEach([SurfaceRole.accent, .accentHover, .accentPressed], id: \.self) { role in
                    Text(role.rawValue)
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.onAccent))
                        .padding(.horizontal, Spacing.section.points)
                        .padding(.vertical, Spacing.regular.points)
                        .background(appearance.swiftUI(role), in: Capsule())
                }
                Circle()
                    .fill(appearance.swiftUI(LineRole.focusRing))
                    .frame(width: 28, height: 28)
                    .overlay(Text("focus").font(.system(size: 7)).foregroundStyle(.white))
            }
        }
    }
}

/// Radii, spacing and elevation, drawn at size — the three things a hex value cannot show.
struct ShapeSheet: View {
    let appearance: Appearance

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.section.points) {
            Header("Shape and depth", appearance: appearance, note: appearance.scheme.rawValue)

            Caption("radius", appearance: appearance)
            HStack(spacing: Spacing.loose.points) {
                ForEach(Radius.allCases, id: \.self) { radius in
                    VStack(spacing: Spacing.tight.points) {
                        RoundedRectangle(cornerRadius: radius.points, style: .continuous)
                            .fill(appearance.swiftUI(SurfaceRole.panel))
                            .overlay(
                                RoundedRectangle(cornerRadius: radius.points, style: .continuous)
                                    .strokeBorder(appearance.swiftUI(LineRole.borderStrong), lineWidth: 1)
                            )
                            .frame(width: 96, height: 56)
                        Text("\(radius.rawValue) \(Int(radius.points))")
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    }
                }
            }

            Caption("elevation — only for things above the window", appearance: appearance)
            HStack(spacing: Spacing.page.points) {
                ForEach(Elevation.allCases, id: \.self) { level in
                    VStack(spacing: Spacing.snug.points) {
                        RoundedRectangle(cornerRadius: Radius.container.points, style: .continuous)
                            .fill(appearance.swiftUI(SurfaceRole.panel))
                            .frame(width: 116, height: 76)
                            .floating(level)
                        Text(level.rawValue)
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    }
                }
            }
            .padding(.bottom, Spacing.section.points)

            Caption("spacing", appearance: appearance)
            VStack(alignment: .leading, spacing: Spacing.tight.points) {
                ForEach(Spacing.allCases, id: \.self) { step in
                    HStack(spacing: Spacing.snug.points) {
                        Rectangle()
                            .fill(appearance.swiftUI(SurfaceRole.accent))
                            .frame(width: step.points, height: 10)
                        Text("\(step.rawValue) \(Int(step.points))")
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    }
                }
            }
        }
        .padding(Spacing.page.points)
        .background(appearance.swiftUI(SurfaceRole.base))
    }
}

struct Header: View {
    let title: String
    let appearance: Appearance
    let note: String

    init(_ title: String, appearance: Appearance, note: String) {
        self.title = title
        self.appearance = appearance
        self.note = note
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(Typography.title.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            Spacer()
            Text(note)
                .font(Typography.data.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        }
    }
}

/// The quiet grey section label the references use everywhere.
struct Caption: View {
    let text: String
    let appearance: Appearance

    init(_ text: String, appearance: Appearance) {
        self.text = text
        self.appearance = appearance
    }

    var body: some View {
        Text(text.uppercased())
            .font(Typography.caption.font)
            .tracking(0.8)
            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
    }
}
