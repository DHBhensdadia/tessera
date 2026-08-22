import DesignSystem
import SwiftUI

/// The application's front door.
///
/// With a document model the welcome window is where a session starts: there is no
/// document to open by default and an empty project window would be a lie. Xcode's is the
/// reference, and Decision #26 settled that other projects are other *windows* rather than
/// a list inside one.
///
/// **This is the frame, not the finished room.** Recent Projects, the sample project and
/// the three-step creation sheet arrive in part 2; what is here now is the two actions
/// that part 1 needs in order to open two projects at once, drawn with the real design
/// system rather than sketched.
struct WelcomeWindow: View {
    @Environment(\.openWindow) private var openWindow
    @State private var requests = OpenRequests.shared
    @Environment(\.engineRegistry) private var registry
    @State private var recents = RecentProjects()
    @State private var setup = ProjectSetup()
    @State private var isCreating = false
    @Environment(\.colorScheme) private var colourScheme

    private var appearance: Appearance {
        Appearance(scheme: colourScheme == .dark ? .dark : .light)
    }

    var body: some View {
        HStack(spacing: 0) {
            actions
            Rectangle()
                .fill(appearance.swiftUI(LineRole.border))
                .frame(width: 1)
            recentColumn
        }
        .frame(width: 720, height: 420)
        .windowGlass(appearance)
        .onAppear {
            ProjectChooser.openArgumentsGiven(using: registry, openWindow)
            // `--new` opens the creation sheet at launch. The same reasoning as `--open`:
            // the sheet is the largest piece of interface in this phase and the only way
            // to reach it otherwise is a click, which is neither scriptable nor a way to
            // review it in both schemes.
            if CommandLine.arguments.contains("--new") { isCreating = true }
        }
        // The welcome window is the one scene guaranteed to exist, so it is where requests
        // from the Finder are turned into windows. `onChange` rather than `onReceive`:
        // a cold launch by double-click fills the queue before this view appears, and
        // `initial: true` covers exactly that case.
        .onChange(of: requests.pending, initial: true) {
            for url in requests.drain() {
                let location = ProjectLocation(url, intent: .reopen)
                recents.note(location)
                ProjectChooser.show(location, using: registry, openWindow)
            }
        }
        .onChange(of: requests.wantsNewProject) {
            guard requests.wantsNewProject else { return }
            requests.wantsNewProject = false
            setup = ProjectSetup()
            isCreating = true
        }
        .sheet(isPresented: $isCreating) {
            NewProjectSheet(setup: $setup, appearance: appearance) {
                isCreating = false
            } confirm: {
                isCreating = false
                ProjectChooser.create(openWindow, setup: setup)
            }
        }
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: Spacing.section.points) {
            VStack(alignment: .leading, spacing: Spacing.tight.points) {
                Text("Tessera")
                    .font(Typography.title.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                Text("Version \(designSystemVersion)")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }

            VStack(alignment: .leading, spacing: Spacing.snug.points) {
                WelcomeAction("Create New Project…", symbol: "plus.circle", appearance: appearance) {
                    setup = ProjectSetup()
                    isCreating = true
                }
                WelcomeAction("Open Existing Project…", symbol: "folder", appearance: appearance) {
                    ProjectChooser.open(openWindow)
                }
                // Decision #28 calls the sample project the highest-leverage adoption
                // feature in the application; P5 builds it at 7.5. It is drawn now, and
                // disabled, so that arriving does not mean redesigning this column.
                WelcomeAction(
                    "Explore Sample Project",
                    symbol: "play.circle",
                    appearance: appearance,
                    enabled: false
                ) {}
            }
            Spacer()
        }
        .padding(Spacing.page.points)
        .frame(width: 320, alignment: .leading)
    }

    private var recentColumn: some View {
        VStack(alignment: .leading, spacing: Spacing.regular.points) {
            SectionLabel("Recent", appearance: appearance)
            if recents.entries.isEmpty {
                Spacer()
                EmptyState(
                    symbol: "clock",
                    title: "No projects yet",
                    explanation: "Create one, or explore the sample.",
                    appearance: appearance
                )
                Spacer()
            } else {
                ScrollView {
                    VStack(spacing: 0) {
                        let vanished = recents.vanished
                        ForEach(recents.entries) { entry in
                            RecentRow(
                                entry: entry,
                                hasVanished: vanished.contains(entry.url),
                                appearance: appearance,
                                open: {
                                    recents.note(entry.location)
                                    ProjectChooser.show(entry.location, using: registry, openWindow)
                                },
                                forget: { recents.forget(entry.url) }
                            )
                        }
                    }
                }
            }
        }
        .padding(Spacing.page.points)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One row of the welcome window's action list.
struct WelcomeAction: View {
    let label: String
    let symbol: String
    let isEnabled: Bool
    let appearance: Appearance
    let action: () -> Void

    @State private var isHovering = false

    init(
        _ label: String,
        symbol: String,
        appearance: Appearance,
        enabled: Bool = true,
        action: @escaping () -> Void
    ) {
        self.label = label
        self.symbol = symbol
        self.isEnabled = enabled
        self.appearance = appearance
        self.action = action
    }

    var body: some View {
        HStack(spacing: Spacing.regular.points) {
            Image(systemName: symbol)
                .font(.system(size: 15, weight: .regular))
                .frame(width: 20)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            Text(label)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            Spacer()
        }
        .opacity(isEnabled ? 1 : 0.4)
        .padding(.vertical, Spacing.snug.points)
        .padding(.horizontal, Spacing.regular.points)
        .background {
            if isHovering {
                RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                    .fill(appearance.swiftUI(SurfaceRole.hover))
            }
        }
        .contentShape(.rect)
        .onHover { isHovering = isEnabled && $0 }
        .onTapGesture { if isEnabled { action() } }
        .animation(Motion.control.animation(appearance), value: isHovering)
    }
}

/// One project in the welcome window's Recent column.
///
/// A project whose file is no longer there is **dimmed and labelled**, not removed. It may
/// be on an external disk that is not mounted, or a share that is not reachable right now,
/// and deleting the entry would throw away the path the person needs in order to go and
/// find it. Forgetting stays a choice they make.
struct RecentRow: View {
    let entry: RecentProjects.Entry
    let hasVanished: Bool
    let appearance: Appearance
    let open: () -> Void
    let forget: () -> Void

    @State private var isHovering = false

    var body: some View {
        HStack(spacing: Spacing.regular.points) {
            VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                Text(entry.location.name)
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                    .lineLimit(1)
                Text(hasVanished ? "Not where it was — \(entry.location.folder)" : entry.location.folder)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(hasVanished ? TextRole.warning : TextRole.secondary))
                    .lineLimit(1)
            }
            Spacer(minLength: Spacing.snug.points)
            if isHovering && hasVanished {
                Button("Forget", action: forget)
                    .buttonStyle(.plain)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            } else {
                Text(entry.openedAt.formatted(.relative(presentation: .numeric)))
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    .lineLimit(1)
            }
        }
        .padding(.vertical, Spacing.snug.points)
        .padding(.horizontal, Spacing.regular.points)
        .opacity(hasVanished ? 0.55 : 1)
        .background {
            if isHovering {
                RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                    .fill(appearance.swiftUI(SurfaceRole.hover))
            }
        }
        .contentShape(.rect)
        .onHover { isHovering = $0 }
        .onTapGesture(perform: open)
        .animation(Motion.control.animation(appearance), value: isHovering)
    }
}
