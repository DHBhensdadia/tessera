import AppKit
import Observation

/// Projects the system has asked us to open, waiting for a scene to open them.
///
/// Double-clicking a `.tessera` in the Finder arrives as an AppleEvent on the application
/// delegate, which is AppKit, and windows are opened by `openWindow`, which is SwiftUI and
/// only reachable from inside a view. Something has to carry a URL across that gap.
///
/// A queue rather than a single value, because macOS delivers several at once when the
/// user selects three projects and presses ⌘O — and because the request can arrive before
/// there is any scene to receive it, on a cold launch by double-click.
@Observable
@MainActor
final class OpenRequests {
    /// One instance, because the delegate that fills it is itself a singleton and there is
    /// nowhere earlier to put it. Deliberately the only global in the application.
    static let shared = OpenRequests()

    private(set) var pending: [URL] = []

    /// Somebody asked for a new project from a menu.
    ///
    /// The creation sheet lives in the welcome window, because it has to finish before any
    /// engine exists and the welcome window is the one scene that is always available. ⌘N
    /// pressed in a project window therefore has to travel here, the same way a
    /// double-click does.
    var wantsNewProject = false

    func request(_ urls: [URL]) {
        pending.append(contentsOf: urls)
    }

    /// Hand over everything waiting, exactly once.
    ///
    /// Draining rather than reading means two scenes observing this cannot both open the
    /// same project — which would be harmless (one window per value) but would also open a
    /// second engine's worth of work before SwiftUI collapsed them.
    func drain() -> [URL] {
        defer { pending.removeAll() }
        return pending
    }
}
