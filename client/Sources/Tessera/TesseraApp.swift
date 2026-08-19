import DesignSystem
import SwiftUI

/// Makes a binary launched from a terminal behave like an application.
///
/// The packaged `.app` has an `Info.plist` and is already a regular application, so this
/// is a no-op there. It matters for `swift run Tessera` during development: without it
/// macOS treats the process as an accessory, which means no Dock icon, no focus, and a
/// window that can sit behind whatever was already frontmost — indistinguishable from a
/// launch that failed.
final class LaunchDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
}

@main
struct TesseraApp: App {
    @NSApplicationDelegateAdaptor(LaunchDelegate.self) private var launch
    @State private var engine = EngineController()

    var body: some Scene {
        WindowGroup("Tessera") {
            StatusView(engine: engine)
                .task { await engine.start() }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
