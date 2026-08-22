import DesignSystem
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
    private var engine: EngineController { registry.controller(for: location) }

    private var appearance: Appearance {
        Appearance(scheme: colourScheme == .dark ? .dark : .light)
    }

    var body: some View {
        Group {
            if case .unopenable(let problem) = engine.state {
                UnopenableProject(problem: problem, appearance: appearance)
            } else {
                StatusView(engine: engine)
            }
        }
        .frame(minWidth: 860, minHeight: 560)
        .navigationTitle(location.name)
        // The path is what makes the proxy icon and the title-bar menu work, and what
        // tells the Finder which file this window is showing. It is also how the
        // application answers "is this project already open" — see `EngineRegistry`.
        .navigationDocument(location.url)
        .task(id: location) {
            await engine.start()
            await applySetupIfNew()
        }
        // Not `.onDisappear` — see `WindowLifetime`. A view leaving a hierarchy is not a
        // window closing, and treating it as one leaked engines.
        .onWindowClose { registry.release(location) }
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
        let api = EngineAPI(port: running.port, token: running.token)
        do {
            let institution = try await api.createInstitution(name: setup.institution)
            let grid = try await api.createTimeGrid(
                institution: institution.id,
                days: setup.grid.days,
                slotsPerDay: setup.grid.slotsPerDay,
                slotMinutes: setup.grid.slotMinutes,
                dayStartMinute: setup.grid.startMinute,
                breakSlots: setup.grid.breakSlots
            )
            _ = try await api.createTerm(
                institution: institution.id,
                timeGrid: grid.id,
                academicYear: setup.academicYear,
                name: setup.termName
            )
        } catch {
            engine.reportSetupFailure(String(describing: error))
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
