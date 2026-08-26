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
        if CommandLine.arguments.contains("--capture") {
            // Repeatedly, not once. A single shot at 1.5 s races the thing it is pinning:
            // the welcome window exists by then, but a project window asked for with
            // `--open` is created in that window's `.onAppear` and can arrive seconds
            // later — after which it is never pinned, opens on whichever Space the process
            // started on, and is invisible to `CGWindowListCopyWindowInfo`'s on-screen
            // list. The symptom is an application that is running, has started an engine,
            // and appears to have no windows at all.
            for delay in stride(from: 1.5, through: 30.0, by: 1.5) {
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { Self.pinToEverySpace() }
            }
        }
        if CommandLine.arguments.contains("--probe") {
            Task { await Probe.run() }
        }
        if let seconds = Self.closeAfter {
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { Self.closeOneProject() }
        }
    }

    /// `--capture` pins every window to all Spaces, so a script can photograph one.
    ///
    /// A process launched from a terminal opens its windows on the Space it *started* on,
    /// which on a machine using full-screen apps is routinely not the one in front. The
    /// window is then genuinely open, absent from the on-screen window list, and impossible
    /// to capture — which looks exactly like an application that failed to start. The
    /// gallery learned this in 3.1b; the application needs it for the same reason, and will
    /// need it more once 3.4 has screens worth looking at.
    ///
    /// Behind a flag because a window that follows you between desktops is wrong for
    /// ordinary use.
    /// `--close-after <seconds>` closes one project window on a timer.
    ///
    /// Exists to verify the one thing about engine teardown that has no other headless
    /// route: that closing a window actually stops its engine. `performClose` is precisely
    /// what ⌘W sends, so the `NSWindow.willCloseNotification` this exercises is the same
    /// one a person triggers — the alternative was to assume it, and this phase has already
    /// found four lifecycle faults that looked correct until they were measured.
    static var closeAfter: Double? {
        guard let index = CommandLine.arguments.firstIndex(of: "--close-after"),
              index + 1 < CommandLine.arguments.count
        else { return nil }
        return Double(CommandLine.arguments[index + 1])
    }

    @MainActor
    private static func closeOneProject() {
        // A project window is one carrying a represented URL; the welcome window has none.
        NSApplication.shared.windows
            .first { $0.representedURL != nil && $0.isVisible }?
            .performClose(nil)
    }

    @MainActor private static var lastReported = ""

    @MainActor
    private static func pinToEverySpace() {
        let windows = NSApplication.shared.windows
        for window in windows {
            window.collectionBehavior.insert(.canJoinAllSpaces)
            window.orderFrontRegardless()
        }
        // Say what was pinned, on stderr where the rest of the development output goes.
        //
        // A capture flag that silently photographs one of eighteen identical windows is
        // worse than one that fails, because the picture looks right. This is how the
        // duplicate-window fault below was found: `screencapture` started refusing a window
        // id that `CGWindowListCopyWindowInfo` was perfectly happy to hand out.
        let described = windows.map { window -> String in
            window.representedURL?.lastPathComponent
                ?? (window.title.isEmpty ? "untitled" : window.title)
        }
        // Only when it changes. The pin now runs twenty times, and twenty identical lines
        // would bury the one that matters.
        let line = "capture: \(windows.count) window(s) — \(described.joined(separator: ", "))"
        guard line != lastReported else { return }
        lastReported = line
        FileHandle.standardError.write(Data((line + "\n").utf8))
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
