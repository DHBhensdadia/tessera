import AppKit
import SwiftUI

/// Makes the window itself translucent, so the desktop is visible through the chrome.
///
/// This is the difference between an application that *uses* a frosted panel and one that
/// looks like the references. In four of the twelve, the wallpaper, a photograph or a
/// landscape is plainly visible behind the interface — the window is a pane of glass, not
/// an opaque rectangle with a frosted card on it.
///
/// SwiftUI has no first-class way to say this on macOS 14, so it goes through
/// `NSVisualEffectView`, which is what the platform has always used and what every
/// translucent Apple application is built on.
public struct WindowBackground: NSViewRepresentable {
    private let appearance: Appearance

    public init(_ appearance: Appearance) {
        self.appearance = appearance
    }

    public func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        // `.behindWindow` samples what is *behind the window*; `.withinWindow` samples the
        // application's own content. Only the first gives the effect the references show.
        view.blendingMode = .behindWindow
        // Stays translucent when the window is not frontmost. The default goes opaque on
        // deactivation, which makes a window flicker between two designs as focus moves.
        view.state = .active
        return view
    }

    public func updateNSView(_ view: NSVisualEffectView, context: Context) {
        // `.underWindowBackground` is the material Apple uses for exactly this job, and it
        // adapts to the desktop rather than tinting it a fixed colour.
        view.material = appearance.reduceTransparency ? .contentBackground : .underWindowBackground
        view.appearance = NSAppearance(named: appearance.scheme == .dark ? .darkAqua : .aqua)
    }
}

extension View {
    /// Put the window's glass behind this view.
    ///
    /// Under Reduce Transparency the material becomes an opaque one rather than the view
    /// being removed, so the layout is identical either way — a window that changes size
    /// or spacing with an accessibility setting is a second design to maintain.
    public func windowGlass(_ appearance: Appearance) -> some View {
        background(WindowBackground(appearance).ignoresSafeArea())
    }
}
