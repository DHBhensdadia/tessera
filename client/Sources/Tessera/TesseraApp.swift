import DesignSystem
import SwiftUI

/// Makes a binary launched from a terminal behave like an application.
///
/// The packaged `.app` has an `Info.plist` and is already a regular application, so this
/// is a no-op there. It matters for `swift run Tessera` during development: without it
/// macOS treats the process as an accessory, which means no Dock icon, no focus, and a
/// window that can sit behind whatever was already frontmost — indistinguishable from a
/// launch that failed.
///
/// It does **not** rescue a bundled app whose binary is executed directly rather than
/// launched through LaunchServices. That path runs this delegate and then presents no
/// scenes at all — an application with a Dock icon, a menu bar and zero windows, at nine
/// seconds and at ninety. `open -n Tessera.app --args …` is how a user starts it and
/// therefore the only way to verify it; an hour went into bisecting the scene code for a
/// fault that was in the way it was being launched.
final class LaunchDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    /// Closing the last project window leaves the welcome window, not an empty Dock icon
    /// with no way back in.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    /// A project double-clicked in the Finder, or dropped on the Dock icon.
    ///
    /// Always a reopen: the Finder can only hand us something that exists, and a project
    /// that has been deleted between the click and the launch must fail rather than be
    /// re-created empty.
    func application(_ application: NSApplication, open urls: [URL]) {
        MainActor.assumeIsolated { OpenRequests.shared.request(urls) }
    }
}

/// Two scenes, because a project is a file and the front door is not one.
///
/// **Not `DocumentGroup`.** That scene is built around `FileDocument`: the framework reads
/// the file into a value, hands it to the view and writes it back. Our document is a
/// SQLite database inside a package, mutated by a subprocess, with no in-memory
/// representation and no save step at all — P7 is explicit that there is no Save button.
/// Adopting it would mean writing a document type that reads nothing, writes nothing and
/// lies about both, in exchange for menu items that are forty lines to write. It also
/// opens an open-panel at launch, which is precisely what a welcome window is instead of.
///
/// `WindowGroup(for:)` earns its place on one guarantee: **one window per value**. Asking
/// to open a project that is already open focuses the window that has it rather than
/// starting a second engine against the same database — which is the failure the
/// one-engine-per-project rule exists to prevent, and which nothing else here would catch.
@main
struct TesseraApp: App {
    @NSApplicationDelegateAdaptor(LaunchDelegate.self) private var launch
    @State private var registry = EngineRegistry()

    var body: some Scene {
        Window("Welcome to Tessera", id: WindowID.welcome) {
            WelcomeWindow()
                .environment(\.engineRegistry, registry)
        }
        .windowResizability(.contentSize)
        .defaultPosition(.center)

        WindowGroup(for: ProjectLocation.self) { $location in
            if let location {
                ProjectWindow(location: location)
                    .environment(\.engineRegistry, registry)
            }
        }
        .commands { ProjectCommands() }
    }
}

enum WindowID {
    static let welcome = "welcome"
}

/// The menu items `DocumentGroup` would have supplied.
///
/// `New` and `Open` sit in the File menu where macOS users reach for them; the welcome
/// window offers the same two actions to people who have not learned the menu bar yet.
/// Both routes go through the same two functions, so there is one definition of what
/// opening a project means.
struct ProjectCommands: Commands {
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("New Project…") {
                OpenRequests.shared.wantsNewProject = true
                openWindow(id: WindowID.welcome)
            }
            .keyboardShortcut("n")
            Button("Open Project…") { ProjectChooser.open(openWindow) }
                .keyboardShortcut("o")
        }
        CommandGroup(after: .windowList) {
            Button("Welcome to Tessera") { openWindow(id: WindowID.welcome) }
                .keyboardShortcut("1", modifiers: [.command, .shift])
        }
    }
}
