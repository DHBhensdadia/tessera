import AppKit
import SwiftUI

/// The two panels, and the single place that decides what opening a project means.
///
/// Both the File menu and the welcome window call these, so "open" cannot come to mean
/// two different things depending on which route the user took — which matters more than
/// it sounds, because the two routes carry **different intents**, and the intent is what
/// stands between a missing project and an empty one wearing its name.
enum ProjectChooser {
    /// Open a project, or bring it forward if it is already open.
    ///
    /// Every route into a project window goes through here — the File menu, the welcome
    /// window, Recent Projects, a Finder double-click, a launch argument — so "already
    /// open" cannot mean one thing in one place and something else in another.
    ///
    /// The check exists because `WindowGroup(for:)` does not do it. The plan assumed it
    /// would; the process tree said otherwise.
    @MainActor
    static func show(
        _ location: ProjectLocation,
        using registry: EngineRegistry,
        _ openWindow: OpenWindowAction
    ) {
        // Recorded before the window exists, so the window can ask whether it was wanted.
        registry.note(location)
        guard !registry.focusIfOpen(location) else { return }
        openWindow(value: location)
    }

    /// A save panel, because creating a project is choosing where a file goes. macOS
    /// handles the overwrite confirmation, so this does not have to.
    @MainActor
    static func create(_ openWindow: OpenWindowAction, setup: ProjectSetup) {
        let panel = NSSavePanel()
        panel.title = "New Project"
        panel.prompt = "Create"
        panel.nameFieldStringValue = suggestedName(for: setup)
        panel.allowedContentTypes = [.tesseraProject]
        panel.canCreateDirectories = true

        guard panel.runModal() == .OK, let url = panel.url else { return }
        openWindow(value: ProjectLocation(url, intent: .create, setup: setup))
    }

    /// What the save panel offers to call it.
    ///
    /// The user has already typed an institution and a term by the time they get here, so
    /// asking them to invent a filename from nothing is a question with an obvious answer
    /// the application declined to give.
    static func suggestedName(for setup: ProjectSetup) -> String {
        let institution = setup.institution.trimmingCharacters(in: .whitespaces)
        let term = setup.termName.trimmingCharacters(in: .whitespaces)
        let year = setup.academicYear.trimmingCharacters(in: .whitespaces)
        let parts = [institution, [term, year].filter { !$0.isEmpty }.joined(separator: " ")]
        let name = parts.filter { !$0.isEmpty }.joined(separator: " — ")
        return name.isEmpty ? "Timetables" : name
    }

    /// An open panel restricted to our own type. A `.tessera` is a package, so it has to
    /// be selectable as a *file* rather than traversed as the directory it really is.
    @MainActor
    static func open(_ openWindow: OpenWindowAction) {
        let panel = NSOpenPanel()
        panel.title = "Open Project"
        panel.allowedContentTypes = [.tesseraProject]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.treatsFilePackagesAsDirectories = false

        guard panel.runModal() == .OK, let url = panel.url else { return }
        openWindow(value: ProjectLocation(url, intent: .reopen))
    }

    /// Projects named on the command line, opened at launch.
    ///
    ///     Tessera --open ~/Timetables/Autumn.tessera --open ~/Timetables/Spring.tessera
    ///
    /// A development affordance, and the same reasoning as the gallery's flags: the
    /// alternative for checking that two projects really do get two windows and two
    /// engines is driving a modal open panel, which is neither scriptable nor honest
    /// about what it proves. Until the Finder can hand us a document — part 2's type
    /// declaration — this is the only route into the application that a script can take.
    ///
    /// Always `.reopen`: something named on a command line is something the caller
    /// believes already exists, and a typo must not create a project.
    /// Queued rather than opened directly, which is not a detail.
    ///
    /// This runs from the welcome window's `.onAppear`, and calling `openWindow(value:)`
    /// from inside another scene's appearance is **too early** — SwiftUI drops the request
    /// and no window is ever presented. The application then sits there with a Dock icon,
    /// no windows, and no error: `--open` looked like it worked for months only because
    /// scene restoration was separately reopening the same project and presenting *that*.
    /// Clearing the saved windows is what finally made it visible.
    ///
    /// So it goes into `OpenRequests`, the queue the Finder already uses. That queue is
    /// drained by an `onChange` a turn later, when the scene is ready — and there is now
    /// one route into the application rather than two that behave differently.
    @MainActor
    static func openArgumentsGiven() {
        let arguments = CommandLine.arguments
        let urls = arguments.enumerated().compactMap { index, argument -> URL? in
            guard argument == "--open", index + 1 < arguments.count else { return nil }
            return URL(filePath: arguments[index + 1])
        }
        guard !urls.isEmpty else { return }
        OpenRequests.shared.request(urls)
    }
}
