import SwiftUI

/// The states any interactive control has to answer for.
///
/// Enumerated rather than left to each component, because "we forgot the disabled state"
/// is the commonest hole in a design system and it is invisible until somebody disables
/// something. A test asserts every registered control names all of these.
public enum ControlState: String, CaseIterable, Sendable {
    case normal, hover, pressed, focused, disabled

    /// Whether the control still responds. Used by components to decide tint, and by the
    /// gallery to label the specimen honestly.
    public var isEnabled: Bool { self != .disabled }
}

/// Where a control's state comes from.
///
/// Until 3.1c there was no such thing: `ControlState` was a parameter every caller passed,
/// which meant the hover and pressed colours — and the test guarding that they are all
/// visually distinct — described renderings **no user could ever reach**. There is no
/// `onHover` anywhere in the codebase before this. The states existed, were enumerated,
/// were proved distinct, and were unreachable.
///
/// So a control tracks its own state now, and pinning is the exception rather than the
/// rule. Pinning stays because a specimen has to show a state that otherwise lasts 120
/// milliseconds, and because a test needs to construct one without a window.
public enum StateSource: Equatable, Sendable {
    /// The control follows the pointer, the press and the focus itself. Every real screen.
    case live
    /// Held at one state. The gallery, the snapshot sheets, and tests.
    case pinned(ControlState)

    /// What to draw, given what the control has observed about itself.
    ///
    /// Precedence, and the reason for it: `disabled` outranks everything because a control
    /// that cannot be used must not look like it is about to be; `pressed` outranks
    /// `focused` because the press is happening *now*; `focused` outranks `hover` because
    /// focus persists after the pointer leaves and losing the ring on mouse-out is how
    /// keyboard users lose their place.
    func resolve(hovering: Bool, pressing: Bool, focused: Bool, enabled: Bool) -> ControlState {
        if case .pinned(let state) = self { return state }
        if !enabled { return .disabled }
        if pressing { return .pressed }
        if focused { return .focused }
        if hovering { return .hover }
        return .normal
    }
}

/// How much visual weight a control carries.
public enum Emphasis: String, CaseIterable, Sendable {
    /// The one action a screen is for. At most one per view.
    case primary
    /// Everything else that is a button.
    case secondary
    /// Destructive, and styled so it cannot be mistaken for the other two.
    case destructive
}

/// A button, resolved entirely from tokens.
///
/// `ActionButton` rather than `Button`: a design system that shadows `SwiftUI.Button`
/// makes every consumer disambiguate, and the compiler's error when they forget is about
/// a missing argument label rather than about the collision.
///
/// It takes an `Appearance` rather than reading the environment so that the gallery can
/// show all sixteen combinations side by side on one screen — which is the only way to
/// review them honestly — and so tests can construct one without a window.
public struct ActionButton<Label: View>: View {
    private let emphasis: Emphasis
    let source: StateSource
    private let isEnabled: Bool
    private let appearance: Appearance
    private let action: () -> Void
    private let label: Label

    @State private var isHovering = false
    @FocusState private var isFocused: Bool

    /// A live button. What every screen uses.
    public init(
        emphasis: Emphasis = .secondary,
        enabled: Bool = true,
        appearance: Appearance,
        action: @escaping () -> Void = {},
        @ViewBuilder label: () -> Label
    ) {
        self.emphasis = emphasis
        self.source = .live
        self.isEnabled = enabled
        self.appearance = appearance
        self.action = action
        self.label = label()
    }

    /// A button held at one state, for a specimen or a test.
    public init(
        emphasis: Emphasis = .secondary,
        state: ControlState,
        appearance: Appearance,
        action: @escaping () -> Void = {},
        @ViewBuilder label: () -> Label
    ) {
        self.emphasis = emphasis
        self.source = .pinned(state)
        self.isEnabled = state.isEnabled
        self.appearance = appearance
        self.action = action
        self.label = label()
    }

    public var body: some View {
        SwiftUI.Button(action: action) { label }
            .buttonStyle(
                TokenButtonStyle(
                    emphasis: emphasis,
                    source: source,
                    hovering: isHovering,
                    focused: isFocused,
                    enabled: isEnabled,
                    appearance: appearance
                )
            )
            .focused($isFocused)
            .disabled(!isEnabled)
            // The pointer half of the state. `onHover` is fed a `false` on the way out by
            // AppKit, including when the window loses key, so a button cannot be left
            // stuck looking hovered after the pointer has gone somewhere else.
            .onHover { hovering in
                guard isEnabled else { return }
                isHovering = hovering
            }
    }
}

/// The whole visual definition of a button, in one place.
struct TokenButtonStyle: ButtonStyle {
    let emphasis: Emphasis
    let source: StateSource
    var hovering: Bool = false
    var focused: Bool = false
    var enabled: Bool = true
    let appearance: Appearance

    /// The press comes from the style rather than from the view: `isPressed` is the one
    /// piece of state SwiftUI will not hand to the enclosing view, and reimplementing it
    /// with a drag gesture is how a button stops respecting the "drag off to cancel"
    /// behaviour every other control on the platform has.
    func state(pressing: Bool) -> ControlState {
        source.resolve(hovering: hovering, pressing: pressing, focused: focused, enabled: enabled)
    }

    func makeBody(configuration: Configuration) -> some View {
        let state = state(pressing: configuration.isPressed)
        return configuration.label
            .font(Typography.body.font)
            .foregroundStyle(appearance.swiftUI(foregroundRole))
            .padding(.horizontal, emphasis == .primary ? Spacing.section.points : Spacing.regular.points)
            .padding(.vertical, Spacing.snug.points)
            .background(appearance.swiftUI(backgroundRole(state)), in: shape)
            .overlay(
                shape.strokeBorder(
                    appearance.swiftUI(borderRole),
                    lineWidth: emphasis == .primary ? 0 : 1
                )
            )
            .overlay(focusRing(state))
            // A disabled control is dimmed rather than recoloured, so its shape and
            // position stay readable — you can still see what it *would* do.
            .opacity(state == .disabled ? 0.45 : 1)
            .animation(Motion.control.animation(appearance), value: state)
    }

    /// The primary action is a **pill**; everything else is a rounded rectangle.
    ///
    /// Both light references do this — the one action a screen is for is a capsule, and
    /// the rest are not — and it does more work than it looks. Shape distinguishes the
    /// primary action even where colour cannot: in monochrome, at a glance, or for someone
    /// who cannot separate the accent from the surface behind it.
    /// Not private, for the same reason the role choices are not: the shape a component
    /// picks is a decision, and a decision with no test is one that gets undone by
    /// accident.
    var radius: Radius { emphasis == .primary ? .pill : .control }

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: radius.points, style: .continuous)
    }

    // Not private: the pairing a component chooses is exactly what a contrast test needs
    // to see. A destructive button whose red landed on the accent would satisfy every
    // palette test and still be unreadable, because the palette does not choose pairings —
    // the component does.
    var foregroundRole: TextRole {
        switch emphasis {
        case .primary: .onAccent
        case .secondary: .primary
        case .destructive: .critical
        }
    }

    func backgroundRole(_ state: ControlState) -> SurfaceRole {
        // Every state gets a distinct surface. The first version returned `.accent` for a
        // primary button in *every* state and `.raised` for both normal and hover, so a
        // filled button had no press feedback and an outlined one no hover — invisible to
        // the tests, obvious the moment the gallery was looked at.
        switch (emphasis, state) {
        case (.primary, .hover): .accentHover
        case (.primary, .pressed): .accentPressed
        case (.primary, _): .accent
        case (_, .hover): .hover
        case (_, .pressed): .selection
        default: .panel
        }
    }

    var borderRole: LineRole {
        // A filled control needs no outline — the fill *is* the edge, and a border on top
        // of a near-black pill only muddies it.
        //
        // An outlined control uses `borderStrong`, not `border`. That is what the roles
        // already say: `border` is a decorative hairline with no contrast minimum, and a
        // control's boundary owes 3:1 under WCAG "Non-text Contrast". Drawn with the
        // separator colour, the secondary and destructive buttons read as floating text
        // rather than as things you can press — visible immediately in a render, and
        // exactly the distinction the two roles exist to make.
        emphasis == .primary ? .focusRing : .borderStrong
    }

    @ViewBuilder
    private func focusRing(_ state: ControlState) -> some View {
        if state == .focused {
            // Sits just outside the control's own outline so both remain visible: a
            // focus ring drawn on top of the border reads as the border changing colour.
            shape
                .strokeBorder(appearance.swiftUI(LineRole.focusRing), lineWidth: 2)
                .padding(-Spacing.hairline.points)
        }
    }
}
