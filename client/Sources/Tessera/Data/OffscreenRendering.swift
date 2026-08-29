import SwiftUI

/// Whether this view tree is being drawn into a bitmap rather than presented in a window.
///
/// `ImageRenderer` renders a `ScrollView` as **nothing**. `ConstraintsScreen` works around
/// it by exposing its blocks outside the scroll container, and that works because a
/// `ScrollView` there is only how a tall screen is made reachable.
///
/// `EntityWorkspace` cannot use the same trick. Scrolling is not incidental to it — a list
/// of two hundred rooms genuinely needs it in a window — so the container has to stay and
/// behave differently in the two settings.
///
/// An environment value rather than a global flag: `ImageRenderer` accepts an environment,
/// and a global would be readable from the running application, where the answer is always
/// no and a stray write would silently stop every list scrolling.
private struct OffscreenRenderingKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var isRenderingOffscreen: Bool {
        get { self[OffscreenRenderingKey.self] }
        set { self[OffscreenRenderingKey.self] = newValue }
    }
}

/// Scrolls in a window; stacks at full height in a bitmap.
///
/// Drawn at full height a list is *more* useful than the windowed one for review, because
/// nothing sits below a fold — which is how 3.5 found a block that had never once been
/// photographed.
struct ScrollsInAWindow<Content: View>: View {
    @Environment(\.isRenderingOffscreen) private var offscreen

    @ViewBuilder var content: Content

    var body: some View {
        if offscreen {
            content
        } else {
            ScrollView { content }
        }
    }
}
