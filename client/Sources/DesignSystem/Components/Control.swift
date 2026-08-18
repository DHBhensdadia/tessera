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
    private let state: ControlState
    private let appearance: Appearance
    private let action: () -> Void
    private let label: Label

    public init(
        emphasis: Emphasis = .secondary,
        state: ControlState = .normal,
        appearance: Appearance,
        action: @escaping () -> Void = {},
        @ViewBuilder label: () -> Label
    ) {
        self.emphasis = emphasis
        self.state = state
        self.appearance = appearance
        self.action = action
        self.label = label()
    }

    public var body: some View {
        SwiftUI.Button(action: action) { label }
            .buttonStyle(
                TokenButtonStyle(emphasis: emphasis, state: state, appearance: appearance)
            )
            .disabled(!state.isEnabled)
    }
}

/// The whole visual definition of a button, in one place.
struct TokenButtonStyle: ButtonStyle {
    let emphasis: Emphasis
    let state: ControlState
    let appearance: Appearance

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typography.body.font)
            .foregroundStyle(appearance.swiftUI(foregroundRole))
            .padding(.horizontal, Spacing.regular.points)
            .padding(.vertical, Spacing.snug.points)
            .background(appearance.swiftUI(backgroundRole), in: shape)
            .overlay(shape.strokeBorder(appearance.swiftUI(borderRole), lineWidth: 1))
            .overlay(focusRing)
            // A disabled control is dimmed rather than recoloured, so its shape and
            // position stay readable — you can still see what it *would* do.
            .opacity(state == .disabled ? 0.45 : 1)
            .animation(Motion.control.animation(appearance), value: state)
    }

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
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

    var backgroundRole: SurfaceRole {
        // Every state gets a distinct surface. The first version returned `.accent` for a
        // primary button in *every* state and `.raised` for both normal and hover, so a
        // filled button had no press feedback and an outlined one no hover — invisible to
        // the tests, obvious the moment the gallery was looked at.
        switch (emphasis, state) {
        case (.primary, .hover): .accentHover
        case (.primary, .pressed): .accentPressed
        case (.primary, _): .accent
        case (_, .hover): .sunken
        case (_, .pressed): .base
        default: .raised
        }
    }

    var borderRole: LineRole {
        emphasis == .primary ? .borderStrong : .border
    }

    @ViewBuilder
    private var focusRing: some View {
        if state == .focused {
            // Sits just outside the control's own outline so both remain visible: a
            // focus ring drawn on top of the border reads as the border changing colour.
            shape
                .strokeBorder(appearance.swiftUI(LineRole.focusRing), lineWidth: 2)
                .padding(-Spacing.hairline.points)
        }
    }
}
