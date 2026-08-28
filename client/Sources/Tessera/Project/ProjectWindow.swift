import DesignSystem
import EngineClient
import SwiftUI

/// One open project, and the engine that serves it.
///
/// The engine is created here rather than by the application, because the engine's own
/// rule is that it serves one project for its whole life (2.9). A controller owned by the
/// app would have to swap projects underneath itself, which is the thing that rule exists
/// to forbid.
///
/// The controller comes from `EngineRegistry` rather than from this view's own `@State`,
/// and that is not a stylistic preference: holding it here created a new controller on
/// every re-evaluation of the struct and started **six engines for one project** on the
/// shipped bundle. The registry keys on the project, so asking twice returns the same
/// engine. `release` on disappear is the other half — without it, closing eight windows
/// would leave eight Python processes running with nothing to talk to.
///
/// **This is the shell's skeleton.** The toolbar, the glass sidebar, the term switcher and
/// the destinations land in part 3; what part 1 owes is a window that owns its engine,
/// reports honestly while it starts, and says something useful when it cannot.
struct ProjectWindow: View {
    let location: ProjectLocation

    @Environment(\.engineRegistry) private var registry
    @Environment(\.colorScheme) private var colourScheme

    /// Where this window was, remembered **per project**.
    ///
    /// Not `@SceneStorage`, which was the obvious choice and does not survive. It persists
    /// into the saved-application-state bundle, and macOS only writes and replays that when
    /// it is restoring scenes — which by default it does **not** do after somebody quits
    /// with ⌘Q. Checked rather than assumed: after a quit there was no
    /// `com.dhbhensdadia.tessera.savedState` at all, and no stored keys anywhere, while the
    /// window *frame* restored correctly because AppKit persists that separately.
    ///
    /// `@AppStorage` keyed by the project's path keeps the property that made
    /// `@SceneStorage` attractive — two projects each remember their own place, which is
    /// what anybody with a draft and a published term open side by side expects — and adds
    /// the one it was chosen for and did not have.
    @AppStorage private var storedDestination: String
    @AppStorage private var isSidebarVisible: Bool

    @State private var summary = ProjectSummary()
    @State private var importing: ImportRequest?

    /// Whether anybody asked for this project, resolved once the view is on screen.
    ///
    /// Nil until then. `registry` is a plain lookup table rather than something observed, so
    /// the answer has to live in state for the button below to be able to change it.
    @State private var wanted: Bool?

    init(location: ProjectLocation) {
        self.location = location
        let key = location.url.path(percentEncoded: false)
        _storedDestination = AppStorage(
            wrappedValue: Destination.overview.rawValue, "destination:\(key)"
        )
        // Decision #27: hidden-by-default is the right end state, but a project opened for
        // the first time shows the sidebar, because an empty window with a hidden navigator
        // is disorienting to somebody who has never seen the application.
        _isSidebarVisible = AppStorage(wrappedValue: true, "sidebar:\(key)")
    }

    private var destination: Binding<Destination> {
        Binding(
            get: { Destination(rawValue: storedDestination) ?? .overview },
            set: { storedDestination = $0.rawValue }
        )
    }

    private var engine: EngineController { registry.controller(for: location) }

    private var appearance: Appearance {
        Appearance(scheme: colourScheme == .dark ? .dark : .light)
    }

    var body: some View {
        Group {
            if wanted == false {
                RestoredProject(location: location, appearance: appearance) {
                    // Now somebody has asked. Recorded on the registry too, so a second
                    // window for the same project agrees rather than asking again.
                    registry.note(location)
                    wanted = true
                    Task { await begin() }
                }
            } else {
                switch engine.state {
                    case .unopenable(let problem):
                    UnopenableProject(problem: problem, appearance: appearance)
                case .failed:
                    StatusView(engine: engine)
                case .running:
                    shell
                case .idle, .starting:
                    StartingUp(engine: engine, appearance: appearance)
                }
            }
        }
        .frame(minWidth: 860, minHeight: 560)
        .navigationTitle(location.name)
        // The path is what makes the proxy icon and the title-bar menu work, and what
        // tells the Finder which file this window is showing.
        .navigationDocument(location.url)
        .task(id: location) {
            // Seeded rather than overridden, so the sidebar still works afterwards and the
            // window remembers where it was put — `--screen` says where to *start*, not
            // where to stay.
            //
            // Only when it differs. `@AppStorage` publishes on every assignment, equal or
            // not, so an unguarded write here invalidated the body on every pass and the
            // window never got past `.idle` — it sat on "Opening…" with no engine, which
            // reads exactly like an engine that failed to start.
            if let requested = Destination.requestedAtLaunch(),
               requested.rawValue != storedDestination {
                storedDestination = requested.rawValue
            }
            // A window macOS restored is one nobody asked for. It does not get an engine —
            // it gets a question. See `RestoredProject` for why it cannot simply be closed.
            if wanted == nil { wanted = registry.wasRequested(location) }
            guard wanted == true else { return }
            await begin()
        }
        // Not `.onDisappear` — see `WindowLifetime`. A view leaving a hierarchy is not a
        // window closing, and treating it as one leaked engines.
        .sheet(item: $importing) { request in
            ImportSheet(request: request, appearance: appearance) {
                importing = nil
                // The counts on the sidebar and the checklist are now wrong by however many
                // rows were written, and they are read from the engine rather than kept
                // here — so the honest refresh is to ask again.
                Task {
                    if case .running(let running) = engine.state {
                        await summary.load(
                            from: EngineConnection(port: running.port, token: running.token)
                        )
                    }
                }
            }
        }
        .onWindow(
            // Restoration replays one window per persisted *opening* rather than per
            // project, so a project opened repeatedly comes back as a stack of identical
            // windows. Every one of them runs this and they all reach the same answer, so
            // the order does not matter — but it has to run once the window exists, because
            // the question is asked of `representedURL`.
            attach: { window in
                // Not written into the saved state, for whatever that is worth on this
                // deployment target — measured as not enough on its own.
                window.isRestorable = false
                // Restoration replays one window per persisted *opening* rather than per
                // project, so a project opened repeatedly comes back as a stack of identical
                // windows. It has to run once the window exists, because the question is
                // asked of `representedURL`, which `.navigationDocument` sets on attach.
                registry.collapseDuplicates(of: location)
            },
            close: { registry.release(location, closing: $0) }
        )
    }

    /// Start the engine and load what the window needs from it.
    ///
    /// Separate from `.task` because it has two callers now: the ordinary one, and the button
    /// on a restored window that turns "nobody asked for this" into "somebody just did".
    private func begin() async {
        await engine.start()
        await applySetupIfNew()
        if case .running(let running) = engine.state {
            await summary.load(from: EngineConnection(port: running.port, token: running.token))
            LaunchClock.shared.noteFirstUsableWindow()
        }
    }

    /// The shell: chrome around a destination.
    ///
    /// The sidebar is glass and the content pane is opaque — the split every reference
    /// makes, and the one that keeps the boundary between them a *material* change rather
    /// than a hairline that vanishes in light mode (#112).
    private var shell: some View {
        HStack(spacing: 0) {
            if isSidebarVisible {
                ProjectSidebar(
                    selection: destination,
                    summary: summary,
                    appearance: appearance
                )
                .frame(width: 232)
                .transition(.move(edge: .leading).combined(with: .opacity))
            }
            content
        }
        .windowGlass(appearance)
        .animation(Motion.panel.animation(appearance), value: isSidebarVisible)
        .toolbar { toolbar }
    }

    /// A screen that manages a collection fills the pane itself — it has its own list,
    /// its own scrolling and its own inspector. Only the read-only panes are wrapped in a
    /// `ScrollView` here; wrapping a list-and-inspector in one produces a page that scrolls
    /// as a whole while the list inside it also scrolls, which is two scrollbars and one
    /// confused user.
    @ViewBuilder
    private var content: some View {
        Group {
            switch destination.wrappedValue {
            case .rooms, .instructors, .courses, .offerings, .groups, .constraints,
                 .buildings, .features, .departments, .programs,
                 .institutions, .grids, .terms:
                if case .running(let running) = engine.state {
                    let connection = EngineConnection(port: running.port, token: running.token)
                    switch destination.wrappedValue {
                    case .rooms:
                        RoomsScreen(
                            connection: connection,
                            term: summary.selectedTerm?.id,
                            appearance: appearance
                        )
                        .id(summary.selectedTerm?.id ?? 0)
                    case .instructors:
                        InstructorsScreen(
                            connection: connection,
                            term: summary.selectedTerm?.id,
                            appearance: appearance
                        )
                        .id(summary.selectedTerm?.id ?? 0)
                    case .courses:
                        CoursesScreen(connection: connection, appearance: appearance)
                    case .groups:
                        GroupsScreen(connection: connection, appearance: appearance)
                    case .offerings:
                        // The one screen whose contents depend on the toolbar. Keyed on the
                        // term so switching terms rebuilds it rather than showing Autumn's
                        // offerings under Spring's heading.
                        OfferingsScreen(
                            connection: connection,
                            term: summary.selectedTerm?.id,
                            appearance: appearance
                        )
                        .id(summary.selectedTerm?.id ?? 0)
                    case .buildings:
                        simple("Buildings", .buildings, "Rooms in it are kept — they simply stop having an address.", connection)
                    case .features:
                        simple("Features", .features, "Rooms lose it, and any session requiring it may no longer fit anywhere.", connection)
                    case .departments:
                        simple("Departments", .departments, "Instructors and courses in it are kept, without a department.", connection)
                    case .constraints:
                        ConstraintsScreen(
                            connection: connection,
                            term: summary.selectedTerm?.id,
                            appearance: appearance
                        )
                        .id(summary.selectedTerm?.id ?? 0)
                    case .institutions:
                        simple("Institution", .institutions, "Everything belonging to it goes too. A project normally has exactly one.", connection)
                    case .grids:
                        GridsScreen(connection: connection, appearance: appearance)
                    case .terms:
                        TermsScreen(connection: connection, appearance: appearance)
                    default:
                        simple("Programmes", .programs, "Student groups under it are kept, without a programme.", connection)
                    }
                } else {
                    StartingUp(engine: engine, appearance: appearance)
                }
            default:
                ScrollView {
                    Group {
                        if destination.wrappedValue == .overview {
                            Overview(
                                summary: summary,
                                appearance: appearance,
                                go: { destination.wrappedValue = $0 },
                                take: importTaker
                            )
                        } else {
                            DestinationPlaceholder(
                                destination: destination.wrappedValue,
                                appearance: appearance
                            )
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(appearance.swiftUI(SurfaceRole.base))
        .overlay(alignment: .leading) {
            if isSidebarVisible {
                Rectangle()
                    .fill(appearance.swiftUI(LineRole.border))
                    .frame(width: 1)
            }
        }
    }

    /// One of the four name-only screens.
    ///
    /// `.id(title)` is what makes switching destinations build a new store rather than
    /// showing buildings under the heading "Features": a different id is a different view
    /// identity, and the screen's `@State` goes with it. The store itself is created inside
    /// the screen — created here, it was rebuilt on every body evaluation and the list
    /// never filled.
    private func simple(
        _ title: String,
        _ operations: SimpleEntityStore.Operations,
        _ warning: String,
        _ connection: EngineConnection
    ) -> some View {
        SimpleEntityScreen(
            title: title,
            deleteWarning: warning,
            connection: connection,
            operations: operations,
            appearance: appearance
        )
        .id(title)
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .navigation) {
            Button {
                isSidebarVisible.toggle()
            } label: {
                Image(systemName: "sidebar.left")
            }
            .help("Hide or show the sidebar")
            .keyboardShortcut("0", modifiers: .command)
        }
        ToolbarItem(placement: .principal) {
            TermSwitcher(summary: summary, appearance: appearance)
        }
        ToolbarItem(placement: .primaryAction) {
            // Disabled rather than absent: the solver is Stage 5, and a toolbar that gains
            // its most important button late is a layout somebody has to redesign.
            Button("Generate") {}
                .disabled(true)
                .help("Generating a timetable arrives with the solver")
        }
    }

    /// Taking a dropped spreadsheet, when there is a term to import into.
    ///
    /// Nil without one, so the drop zone is absent rather than present and refusing: the
    /// engine needs a term to name the institution the rows belong to, and a target that
    /// accepts a file and then explains it cannot is worse than no target.
    private var importTaker: ((ImportStore.Dropped) -> Void)? {
        guard case .running(let running) = engine.state, let term = summary.selectedTerm?.id
        else { return nil }
        let connection = EngineConnection(port: running.port, token: running.token)
        return { dropped in
            importing = ImportRequest(connection: connection, term: term, dropped: dropped)
        }
    }

    /// Fill a brand-new project with what the sheet collected.
    ///
    /// Runs once, after the engine is serving, because there is no database to write into
    /// until then. Failure is surfaced rather than swallowed: a project whose institution
    /// and grid did not get written is empty in a way the user cannot see and cannot fix
    /// from the interface, and silently continuing would leave them to discover it when
    /// the solver has nothing to solve.
    private func applySetupIfNew() async {
        guard let setup = location.setup, case .running(let running) = engine.state else { return }
        let connection = EngineConnection(port: running.port, token: running.token)
        do {
            let institution = try await connection.run {
                try await $0.createInstitution(body: .json(.init(name: setup.institution)))
                    .created.body.json
            }
            let grid = try await connection.run {
                try await $0.createTimeGrid(body: .json(.init(
                    break_slots: setup.grid.breakSlots,
                    day_start_minute: setup.grid.startMinute,
                    days: setup.grid.days,
                    institution_id: institution.id,
                    slot_minutes: setup.grid.slotMinutes,
                    slots_per_day: setup.grid.slotsPerDay
                ))).created.body.json
            }
            _ = try await connection.run {
                try await $0.createTerm(body: .json(.init(
                    academic_year: setup.academicYear,
                    institution_id: institution.id,
                    name: setup.termName,
                    time_grid_id: grid.id
                ))).created.body.json
            }
        } catch {
            // The engine's own sentence, not a description of a Swift error type.
            engine.reportSetupFailure(EngineFailure.unwrap(error).message)
        }
    }
}

/// What a window says when the project it was asked to open is not there.
///
/// A window rather than an alert on purpose: the user asked for this project, so the
/// application owes them a place that is *about* that project rather than a dialog that
/// disappears and leaves an empty screen behind.
struct UnopenableProject: View {
    let problem: ProjectProblem
    let appearance: Appearance

    var body: some View {
        VStack(spacing: Spacing.regular.points) {
            Image(systemName: "questionmark.folder")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            Text(problem.message)
                .font(Typography.heading.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
                .multilineTextAlignment(.center)
            Text(problem.explanation)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                .multilineTextAlignment(.center)
                .frame(maxWidth: 380)
        }
        .padding(Spacing.page.points)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(appearance.swiftUI(SurfaceRole.base))
    }
}

/// A window macOS brought back for a project nobody asked to open.
///
/// **Tessera does not restore projects.** It launches clean and waits for somebody to choose
/// one — and on this deployment target there is no way to stop the window appearing.
/// `NSQuitAlwaysKeepsWindows`, per-window `isRestorable` and closing the window on sight were
/// each tried and each measured: the first two do not reach a SwiftUI `WindowGroup(for:)`,
/// and closing it produced a window that came straight back and sat on "Opening…" for ever,
/// with no engine behind it and no error. `restorationBehavior(.disabled)` is the switch that
/// would work and it needs macOS 15.
///
/// So the window is given something true to say instead of being fought. It costs nothing —
/// no engine is started until somebody asks — and it turns a spinner that never resolves into
/// a question with an answer.
struct RestoredProject: View {
    let location: ProjectLocation
    let appearance: Appearance
    let open: () -> Void

    var body: some View {
        VStack(spacing: Spacing.regular.points) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            Text("\(location.name) was open last time")
                .font(Typography.heading.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
                .multilineTextAlignment(.center)
            Text("Tessera does not reopen projects on its own — each one runs its own engine, "
                 + "and starting several you did not ask for is a cost you never chose. "
                 + "Nothing has been opened yet.")
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            ActionButton(emphasis: .primary, appearance: appearance, action: open) {
                Text("Open \(location.name)")
            }
            .padding(.top, Spacing.snug.points)
        }
        .padding(Spacing.page.points)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(appearance.swiftUI(SurfaceRole.base))
    }
}

