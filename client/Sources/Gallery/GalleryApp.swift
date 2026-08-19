import DesignSystem
import SwiftUI

/// Makes an executable launched from a terminal behave like an application.
///
/// SwiftPM produces a bare binary with no bundle, and macOS treats such a process as an
/// accessory: it opens a window and will not appear in the Dock, will not take focus, and
/// can end up behind whatever was already frontmost. The window is *there* and you cannot
/// find it, which is indistinguishable from a gallery that failed to launch.
final class GalleryDelegate: NSObject, NSApplicationDelegate {
    /// Bring the window to whichever Space is in front.
    ///
    /// Without this the window opens on the Space the process was *launched* from, which
    /// on a machine using full-screen apps is routinely not the one anybody is looking at.
    /// The window is then genuinely open, absent from the on-screen window list, and
    /// impossible to capture — a design tool you cannot see is no better than one that
    /// failed to start.
    ///
    /// Done on a delay rather than here: SwiftUI creates the `WindowGroup`'s window during
    /// launch, and at the moment this method runs `NSApplication.shared.windows` can still
    /// be empty. Hooking `applicationDidBecomeActive` instead is not enough on its own —
    /// if focus never moves to this process, that method never runs at all.
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { Self.present() }
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        Self.present()
    }

    @MainActor
    private static func present() {
        // `--capture` pins the window to every Space. `.moveToActiveSpace` only relocates
        // the window when it is ordered front *by the user*, so a script that launches
        // this and immediately screenshots it can still find nothing on screen. Joining
        // all Spaces is unconditional and therefore scriptable; it is behind a flag
        // because a window that follows you between desktops is wrong for normal use.
        let behaviour: NSWindow.CollectionBehavior =
            CommandLine.arguments.contains("--capture") ? .canJoinAllSpaces : .moveToActiveSpace
        for window in NSApplication.shared.windows {
            window.collectionBehavior.insert(behaviour)
            window.orderFrontRegardless()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct GalleryApp: App {
    @NSApplicationDelegateAdaptor(GalleryDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup("Tessera Design System \(designSystemVersion)") {
            GalleryWindow()
        }
        .defaultSize(width: 1160, height: 780)
        .windowStyle(.hiddenTitleBar)
    }
}

/// The design system, shown as an application rather than as a specimen sheet.
///
/// The earlier gallery listed every component in two columns with the schemes side by
/// side. It was useful for auditing and it could not answer the only question that
/// matters here — *does this look like a thing somebody would use* — because a spec sheet
/// never looks like a product no matter how good the tokens are.
///
/// So this is built the way the references are: a narrow icon rail, a sidebar of sections,
/// a content pane, and glass all the way through. It demonstrates the system by being made
/// of it, which also means every mistake in the system is a mistake you can see here.
struct GalleryWindow: View {
    @State private var entry: Entry = GalleryWindow.startingEntry
    @State private var reduceTransparency = false
    @State private var increaseContrast = false
    @State private var reduceMotion = false
    /// Overridable so the macOS 14–15 appearance can be reviewed on a macOS 26 machine.
    @State private var liquidGlass = Appearance.systemSupportsLiquidGlass
    @State private var hoveredSection: Section?
    @Environment(\.colorScheme) private var colourScheme

    private var appearance: Appearance {
        var value = Appearance(
            scheme: colourScheme == .dark ? .dark : .light,
            reduceTransparency: reduceTransparency,
            increaseContrast: increaseContrast,
            reduceMotion: reduceMotion
        )
        value.supportsLiquidGlass = liquidGlass
        return value
    }

    var body: some View {
        HStack(spacing: 0) {
            rail
            sidebar
            content
        }
        .frame(minWidth: 980, minHeight: 640)
        .windowGlass(appearance)
        // `--light` / `--dark` force the scheme so both can be reviewed, and captured,
        // without changing the appearance of the whole machine to look at one window.
        .preferredColorScheme(GalleryWindow.forcedScheme)
    }

    /// `--entry <name>` opens on one entry, so each pane can be reviewed and captured
    /// without anybody clicking through to it.
    static let startingEntry: Entry = {
        guard let index = CommandLine.arguments.firstIndex(of: "--entry"),
              index + 1 < CommandLine.arguments.count,
              let entry = Entry(rawValue: CommandLine.arguments[index + 1])
        else { return .colour }
        return entry
    }()

    static let forcedScheme: ColorScheme? = {
        let arguments = Set(CommandLine.arguments)
        if arguments.contains("--dark") { return .dark }
        if arguments.contains("--light") { return .light }
        return nil
    }()

    // -- the icon rail ----------------------------------------------------------
    //
    // Narrow, detached from the sidebar, one glyph per section. Four references have one;
    // it is what makes a window read as an application rather than as a document.
    private var rail: some View {
        VStack(spacing: Spacing.snug.points) {
            ForEach(Section.allCases, id: \.self) { item in
                Image(systemName: item.symbol)
                    .font(.system(size: 15, weight: .regular))
                    .frame(width: 32, height: 32)
                    .foregroundStyle(
                        appearance.swiftUI(item == entry.section ? TextRole.primary : TextRole.tertiary)
                    )
                    .background {
                        if item == entry.section {
                            RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                                .fill(appearance.swiftUI(SurfaceRole.selection))
                        } else if hoveredSection == item {
                            RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                                .fill(appearance.swiftUI(SurfaceRole.hover))
                        }
                    }
                    .contentShape(.rect)
                    .onHover { hoveredSection = $0 ? item : (hoveredSection == item ? nil : hoveredSection) }
                    .onTapGesture { entry = item.entries[0] }
                    .animation(Motion.control.animation(appearance), value: hoveredSection)
                    .accessibilityLabel(item.title)
            }
            Spacer()
        }
        .padding(.vertical, Spacing.loose.points)
        .padding(.horizontal, Spacing.snug.points)
        .frame(width: 56)
    }

    // -- the sidebar ------------------------------------------------------------
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: Spacing.loose.points) {
            // Title, then a rule. Five references head their sidebar exactly this way, and
            // it is the smallest possible demonstration of the phase: the title is
            // separated from the list by a line, not by being put inside a box.
            VStack(alignment: .leading, spacing: Spacing.regular.points) {
                Text("Design system")
                    .font(Typography.heading.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                    .padding(.horizontal, Spacing.regular.points)
                Rule(appearance: appearance)
            }

            VStack(alignment: .leading, spacing: Spacing.section.points) {
                ForEach(Section.allCases, id: \.self) { item in
                    VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                        SectionLabel(item.title, appearance: appearance)
                        ForEach(item.entries, id: \.self) { candidate in
                            SidebarEntry(
                                candidate.title,
                                isSelected: candidate == entry,
                                appearance: appearance
                            ) { entry = candidate }
                        }
                    }
                }
            }
            Spacer()
            settings
        }
        .padding(.vertical, Spacing.loose.points)
        .frame(width: 236, alignment: .leading)
    }

    /// The accessibility settings, as controls rather than as a legend — the whole point
    /// is that they can be turned on while looking at the thing they change.
    private var settings: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            SectionLabel("Rendering", appearance: appearance)
            toggle("Reduce Transparency", $reduceTransparency)
            toggle("Increase Contrast", $increaseContrast)
            toggle("Reduce Motion", $reduceMotion)
            toggle("Liquid Glass", $liquidGlass)
            Text(appearance.fillDescription)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                .padding(.horizontal, Spacing.regular.points)
                .padding(.top, Spacing.tight.points)
        }
        .padding(.bottom, Spacing.snug.points)
    }

    private func toggle(_ label: String, _ binding: Binding<Bool>) -> some View {
        Toggle(label, isOn: binding)
            .toggleStyle(.checkbox)
            .font(Typography.caption.font)
            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            .padding(.horizontal, Spacing.regular.points)
    }

    // -- the content pane -------------------------------------------------------
    private var content: some View {
        ScrollViewReader { scroller in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(entry.section.title)
                            .font(Typography.title.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.primary))
                        Spacer()
                        Text(appearance.scheme.rawValue)
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    }
                    // The pane adds no horizontal padding: every `ContentSection` owns its
                    // own inset so that its rule can run the full width. Padding here would
                    // turn each rule into an underline and put the sections out of line
                    // with the header above them.
                    .padding(.horizontal, Spacing.page.points)
                    .padding(.top, Spacing.page.points)
                    .padding(.bottom, Spacing.section.points)

                    Rule(appearance: appearance)

                    switch entry.section {
                    case .foundations: FoundationsPane(appearance: appearance)
                    case .components: ComponentsPane(appearance: appearance)
                    case .data: DataPane(appearance: appearance)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // Selecting an entry inside the section already on screen scrolls to its card
            // rather than redrawing the pane. Without this, half the sidebar would look
            // like it does nothing: six of the eight entries share a pane with another.
            .onChange(of: entry) { _, new in
                withAnimation(Motion.panel.animation(appearance)) {
                    scroller.scrollTo(new, anchor: .top)
                }
            }
        }
        // The content pane is an opaque surface and the chrome around it is glass. That
        // is the split every reference makes, and it is also what makes the boundary
        // between them survive both schemes: a hairline on glass against glass was
        // invisible in light, because there was no material change behind it.
        .background(appearance.swiftUI(SurfaceRole.base))
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(appearance.swiftUI(LineRole.border))
                .frame(width: 1)
        }
    }
}

enum Section: String, CaseIterable {
    case foundations, components, data

    var title: String {
        switch self {
        case .foundations: "Foundations"
        case .components: "Components"
        case .data: "Data"
        }
    }

    var symbol: String {
        switch self {
        case .foundations: "circle.lefthalf.filled"
        case .components: "square.on.square"
        case .data: "tablecells"
        }
    }

    var entries: [Entry] { Entry.allCases.filter { $0.section == self } }
}

/// One thing you can look at. Also the scroll anchor of the card that shows it, which is
/// what lets the sidebar select something already on screen without redrawing the pane.
enum Entry: String, CaseIterable, Hashable {
    case colour, type, shape
    case buttons, fields, empty
    case tables, rows, badges

    var section: Section {
        switch self {
        case .colour, .type, .shape: .foundations
        case .buttons, .fields, .empty: .components
        case .tables, .rows, .badges: .data
        }
    }

    var title: String {
        switch self {
        case .colour: "Colour"
        case .type: "Type"
        case .shape: "Shape"
        case .buttons: "Buttons"
        case .fields: "Fields"
        case .empty: "Empty states"
        case .tables: "Tables"
        case .rows: "List rows"
        case .badges: "Badges"
        }
    }
}

/// A sidebar row. Selected state is a filled rounded rectangle, the way every reference
/// draws it — not a tint on the label, which disappears the moment the window loses focus.
struct SidebarEntry: View {
    let text: String
    let isSelected: Bool
    let appearance: Appearance
    let select: () -> Void

    @State private var isHovering = false

    init(_ text: String, isSelected: Bool, appearance: Appearance, select: @escaping () -> Void) {
        self.text = text
        self.isSelected = isSelected
        self.appearance = appearance
        self.select = select
    }

    var body: some View {
        Text(text)
            .font(Typography.body.font)
            .foregroundStyle(appearance.swiftUI(isSelected ? TextRole.primary : TextRole.secondary))
            .padding(.vertical, Spacing.snug.points)
            .padding(.horizontal, Spacing.regular.points)
            .frame(maxWidth: .infinity, alignment: .leading)
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
    }
}

/// The quiet grey label the references put above every group.
struct SectionLabel: View {
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
            .padding(.horizontal, Spacing.regular.points)
    }
}

extension Appearance {
    /// What is actually being drawn, stated on screen. The whole reason the fill is a
    /// value rather than a branch inside a view is that it can be reported.
    var fillDescription: String {
        switch fill(for: .chrome) {
        case .liquidGlass: "chrome: Liquid Glass"
        case .systemMaterial: "chrome: system material (macOS 14–15)"
        case .solid: "chrome: solid — Reduce Transparency"
        }
    }
}
