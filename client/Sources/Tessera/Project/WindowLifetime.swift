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
    let onClose: () -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        // Attaching happens in `updateNSView`, not here: a view has no window until it has
        // been added to one, and `makeNSView` runs before that.
        context.coordinator.onClose = onClose
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
        context.coordinator.watch(view.window)
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    @MainActor
    final class Coordinator {
        var onClose: () -> Void = {}
        private weak var watched: NSWindow?
        private var token: (any NSObjectProtocol)?

        /// Observe one window, once. Re-running `updateNSView` must not stack observers,
        /// and a view moved between windows must stop watching the old one.
        func watch(_ window: NSWindow?) {
            guard let window, window !== watched else { return }
            if let token { NotificationCenter.default.removeObserver(token) }
            watched = window
            token = NotificationCenter.default.addObserver(
                forName: NSWindow.willCloseNotification,
                object: window,
                queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated {
                    self?.onClose()
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
    func onWindowClose(perform action: @escaping () -> Void) -> some View {
        background(WindowLifetime(onClose: action).frame(width: 0, height: 0))
    }
}
