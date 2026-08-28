import AppKit
import SwiftUI

/// Runs something when the window this view is in genuinely closes.
///
/// `.onDisappear` is not that. SwiftUI fires it whenever a view leaves a hierarchy, which
/// includes re-evaluations that have nothing to do with a window — and hanging engine
/// teardown off it dropped a live controller, let the next lookup build a second one, and
/// left the first Python process running with nothing attached to it. Measured: two
/// projects open produced **three** engines, two of them serving the same database.
///
/// It is the same mistake as the `@State` engine this phase already replaced once —
/// trusting a SwiftUI view callback to mean a *window* event. AppKit has the event we
/// actually want, and it means exactly one thing.
struct WindowLifetime: NSViewRepresentable {
    /// Handed the window that closed, because a caller deciding whether anything *else*
    /// still shows this project has to be able to exclude the one going away — it is still
    /// in `NSApplication.shared.windows`, and still visible, while the notification is
    /// being delivered.
    let onClose: (NSWindow) -> Void
    /// Called once, as soon as this view is in a window.
    ///
    /// `.task` is too early for anything that reads the window: SwiftUI runs it before the
    /// view has one, so `representedURL` — which `.navigationDocument` sets — is still nil.
    /// Anything deciding "is another window already showing this project?" at that point
    /// sees nothing and concludes no.
    let onAttach: (NSWindow) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        // Attaching happens in `updateNSView`, not here: a view has no window until it has
        // been added to one, and `makeNSView` runs before that.
        context.coordinator.onClose = onClose
        context.coordinator.onAttach = onAttach
        // A view has no window until AppKit has added it to one, which happens after this
        // returns — and `updateNSView` is only called again if something upstream changes,
        // which for a settled window is never. So the check is deferred to the next turn
        // of the run loop rather than left to a callback that may not come.
        DispatchQueue.main.async { [weak view] in
            context.coordinator.watch(view?.window)
        }
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        context.coordinator.onClose = onClose
        context.coordinator.onAttach = onAttach
        context.coordinator.watch(view.window)
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    @MainActor
    final class Coordinator {
        var onClose: (NSWindow) -> Void = { _ in }
        var onAttach: (NSWindow) -> Void = { _ in }
        private weak var watched: NSWindow?
        private var token: (any NSObjectProtocol)?

        /// Observe one window, once. Re-running `updateNSView` must not stack observers,
        /// and a view moved between windows must stop watching the old one.
        func watch(_ window: NSWindow?) {
            guard let window, window !== watched else { return }
            // After the window is recorded, so a handler that closes windows cannot
            // re-enter this and stack a second observer.
            defer { onAttach(window) }
            if let token { NotificationCenter.default.removeObserver(token) }
            watched = window
            token = NotificationCenter.default.addObserver(
                forName: NSWindow.willCloseNotification,
                object: window,
                queue: .main
            ) { [weak self, weak window] _ in
                // The window is captured rather than read out of the notification: the
                // observer closure is `@Sendable`, and carrying a `Notification` across
                // that boundary is what Swift 6 refuses. The observer is registered for
                // this one window, so its identity is already known here.
                MainActor.assumeIsolated {
                    if let window { self?.onClose(window) }
                    self?.stopWatching()
                }
            }
        }

        /// Stop watching. Called when the observed window closes, which is also the only
        /// moment this coordinator has anything left to do.
        func stopWatching() {
            if let token { NotificationCenter.default.removeObserver(token) }
            token = nil
            watched = nil
        }
    }
}

extension View {
    /// Tear something down when this view's window closes — and only when it closes.
    func onWindowClose(perform action: @escaping (NSWindow) -> Void) -> some View {
        background(WindowLifetime(onClose: action, onAttach: { _ in }).frame(width: 0, height: 0))
    }

    /// Run something when this view's window exists, and when it closes.
    func onWindow(
        attach: @escaping (NSWindow) -> Void,
        close: @escaping (NSWindow) -> Void
    ) -> some View {
        background(WindowLifetime(onClose: close, onAttach: attach).frame(width: 0, height: 0))
    }
}
