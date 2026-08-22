import DesignSystem
import SwiftUI

/// The navigator: where you are in a project, and how much of it exists.
///
/// Glass, because it is chrome — the same rule that keeps `Material.content` opaque. It
/// samples the desktop through the window rather than tinting the app's own background,
/// which is the distinction #109 was written about.
///
/// The counts are the reason this is more than a list of links. P7 Act 3: *"the sidebar
/// doubles as a completeness indicator"*. A room count of nil renders as nothing rather
/// than as `0`, because "not asked yet" and "none" are different states and only one of
/// them is a prompt.
struct ProjectSidebar: View {
    @Binding var selection: Destination
    let summary: ProjectSummary
    let appearance: Appearance

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.section.points) {
            ForEach(groups, id: \.name) { group in
                VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                    if let name = group.name {
                        SectionLabel(name, appearance: appearance)
                            .padding(.horizontal, Spacing.regular.points)
                            .padding(.bottom, Spacing.tight.points)
                    }
                    ForEach(group.items) { destination in
                        SidebarItem(
                            destination: destination,
                            count: destination.countsEntity.flatMap(summary.count),
                            isSelected: destination == selection,
                            appearance: appearance
                        ) { selection = destination }
                    }
                }
            }
            Spacer()
        }
        .padding(.vertical, Spacing.loose.points)
        .frame(maxHeight: .infinity, alignment: .top)
    }

    /// Destinations in sidebar order, gathered under their headings.
    ///
    /// Derived from the enum rather than listed again here, so a screen added in 3.4
    /// appears without anybody remembering to add it twice.
    private var groups: [(name: String?, items: [Destination])] {
        var order: [String?] = []
        var byName: [String?: [Destination]] = [:]
        for destination in Destination.allCases {
            if byName[destination.section] == nil { order.append(destination.section) }
            byName[destination.section, default: []].append(destination)
        }
        return order.map { ($0, byName[$0] ?? []) }
    }
}

/// One row of the navigator.
struct SidebarItem: View {
    let destination: Destination
    let count: Int?
    let isSelected: Bool
    let appearance: Appearance
    let select: () -> Void

    @State private var isHovering = false

    var body: some View {
        HStack(spacing: Spacing.snug.points) {
            Image(systemName: destination.symbol)
                .font(.system(size: 13, weight: .regular))
                .frame(width: 18)
                .foregroundStyle(appearance.swiftUI(isSelected ? TextRole.primary : TextRole.secondary))
            Text(destination.title)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(isSelected ? TextRole.primary : TextRole.secondary))
            Spacer(minLength: Spacing.snug.points)
            if let count {
                Text("\(count)")
                    .font(Typography.data.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
        }
        .padding(.vertical, Spacing.snug.points)
        .padding(.horizontal, Spacing.regular.points)
        .background {
            if isSelected || isHovering {
                RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                    .fill(appearance.swiftUI(isSelected ? SurfaceRole.selection : SurfaceRole.hover))
            }
        }
        .contentShape(.rect)
        .onHover { isHovering = $0 }
        .onTapGesture(perform: select)
        .animation(Motion.control.animation(appearance), value: isHovering)
        .padding(.horizontal, Spacing.snug.points)
        .accessibilityLabel(count.map { "\(destination.title), \($0)" } ?? destination.title)
    }
}
