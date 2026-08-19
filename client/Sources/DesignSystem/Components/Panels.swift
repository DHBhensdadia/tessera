import SwiftUI

/// A titled block of content on a raised plane.
///
/// `Material.content`, which means it is never glass however new the operating system —
/// Apple's own guidance keeps glass out of the content layer, and here that is a property
/// of the role rather than a thing to remember.
public struct Card<Content: View>: View {
    private let title: String?
    private let appearance: Appearance
    private let content: Content

    public init(title: String? = nil, appearance: Appearance, @ViewBuilder content: () -> Content) {
        self.title = title
        self.appearance = appearance
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            if let title {
                SwiftUI.Text(title)
                    .font(Typography.heading.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
            }
            content
        }
        .padding(Spacing.loose.points)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surface(.content, appearance, radius: .container)
        .overlay(
            RoundedRectangle(cornerRadius: Radius.container.points, style: .continuous)
                .strokeBorder(appearance.swiftUI(LineRole.border), lineWidth: 1)
        )
    }
}

/// One line in a list: a name, optional detail, optional trailing value.
///
/// The shape almost every screen in this application is made of — rooms, instructors,
/// courses, constraints are all a list of these.
public struct Row: View {
    private let title: String
    private let detail: String?
    private let value: String?
    private let isSelected: Bool
    let source: StateSource
    private let appearance: Appearance
    private let select: (() -> Void)?

    @State private var isHovering = false

    public init(
        _ title: String,
        detail: String? = nil,
        value: String? = nil,
        isSelected: Bool = false,
        state: ControlState? = nil,
        appearance: Appearance,
        select: (() -> Void)? = nil
    ) {
        self.title = title
        self.detail = detail
        self.value = value
        self.isSelected = isSelected
        self.source = state.map(StateSource.pinned) ?? .live
        self.appearance = appearance
        self.select = select
    }

    /// What the row is doing, which for a row is only ever hover or nothing — a list row
    /// has no pressed state distinct from the selection it produces.
    private var state: ControlState {
        source.resolve(hovering: isHovering, pressing: false, focused: false, enabled: true)
    }

    public var body: some View {
        HStack(spacing: Spacing.regular.points) {
            VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                SwiftUI.Text(title)
                    .font(Typography.body.font.weight(titleWeight))
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                if let detail {
                    SwiftUI.Text(detail)
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }
            }
            Spacer(minLength: Spacing.snug.points)
            if let value {
                // Monospaced digits so a column of counts or times does not shuffle
                // sideways as the numbers change.
                SwiftUI.Text(value)
                    .font(Typography.data.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            }
        }
        // Taller than it was. Every reference gives a list row real height — a dense
        // table is read by scanning, and scanning needs the eye to have somewhere to rest
        // between lines.
        .padding(.vertical, Spacing.regular.points)
        .padding(.horizontal, Spacing.regular.points)
        .background {
            if isSelected || state == .hover {
                // An inset pill, not a full-bleed band. This is what four of the
                // references do for a selected row, and the inset is the point: the
                // selection reads as an object sitting *in* the list rather than as the
                // list changing colour behind it.
                //
                // Hover and selection are the same shape at two strengths, and both move
                // *away* from the plane behind them rather than toward white. Drawing
                // hover with `panel` — the pane colour, which is near-white in light —
                // made a hovered row read as a card floating on the list, which is the
                // idiom this phase exists to remove.
                RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                    .fill(appearance.swiftUI(isSelected ? SurfaceRole.selection : SurfaceRole.hover))
                    .padding(.horizontal, Spacing.tight.points)
            }
        }
        .contentShape(.rect)
        .onHover { isHovering = $0 }
        .onTapGesture { select?() }
        .animation(Motion.control.animation(appearance), value: state)
    }

    /// A selected row states its own weight, so the title stops relying on colour alone.
    private var titleWeight: Font.Weight { isSelected ? .semibold : .regular }
}

/// A small status marker: published, draft, a violation count.
public struct Badge: View {
    public enum Tone: String, CaseIterable, Sendable {
        case neutral, positive, warning, critical, info

        var text: TextRole {
            switch self {
            case .neutral: .secondary
            case .positive: .positive
            case .warning: .warning
            case .critical: .critical
            case .info: .info
            }
        }
    }

    private let label: String
    private let tone: Tone
    private let appearance: Appearance

    public init(_ label: String, tone: Tone = .neutral, appearance: Appearance) {
        self.label = label
        self.tone = tone
        self.appearance = appearance
    }

    public var body: some View {
        SwiftUI.Text(label)
            .font(Typography.caption.font)
            .foregroundStyle(appearance.swiftUI(tone.text))
            .padding(.horizontal, Spacing.regular.points)
            .padding(.vertical, Spacing.tight.points)
            .background(appearance.swiftUI(SurfaceRole.well), in: Capsule())
            .overlay(Capsule().strokeBorder(appearance.swiftUI(LineRole.border), lineWidth: 1))
    }
}

/// What a screen shows before it has anything to show.
///
/// A first-class component rather than an afterthought, because an empty state is the
/// first thing every new user sees, and "a blank pane" is how software feels broken.
public struct EmptyState: View {
    private let symbol: String
    private let title: String
    private let explanation: String
    private let appearance: Appearance

    public init(symbol: String, title: String, explanation: String, appearance: Appearance) {
        self.symbol = symbol
        self.title = title
        self.explanation = explanation
        self.appearance = appearance
    }

    public var body: some View {
        VStack(spacing: Spacing.regular.points) {
            Image(systemName: symbol)
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            SwiftUI.Text(title)
                .font(Typography.heading.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            SwiftUI.Text(explanation)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                .multilineTextAlignment(.center)
                .frame(maxWidth: 320)
        }
        .padding(Spacing.page.points)
    }
}

/// A labelled text field with room for a validation message.
///
/// The error slot is part of the component rather than something each screen invents,
/// because a form whose messages appear in different places on different screens is a
/// form people stop reading.
public struct Field: View {
    private let label: String
    private let placeholder: String
    private let problem: String?
    let source: StateSource
    private let isEnabled: Bool
    private let appearance: Appearance
    @Binding private var value: String

    @State private var isHovering = false
    @FocusState private var isFocused: Bool

    /// A live field.
    public init(
        label: String,
        placeholder: String = "",
        value: Binding<String>,
        problem: String? = nil,
        enabled: Bool = true,
        appearance: Appearance
    ) {
        self.label = label
        self.placeholder = placeholder
        self._value = value
        self.problem = problem
        self.source = .live
        self.isEnabled = enabled
        self.appearance = appearance
    }

    /// A field held at one state, for a specimen or a test.
    public init(
        label: String,
        placeholder: String = "",
        value: Binding<String>,
        problem: String? = nil,
        state: ControlState,
        appearance: Appearance
    ) {
        self.label = label
        self.placeholder = placeholder
        self._value = value
        self.problem = problem
        self.source = .pinned(state)
        self.isEnabled = state.isEnabled
        self.appearance = appearance
    }

    private var state: ControlState {
        source.resolve(hovering: isHovering, pressing: false, focused: isFocused, enabled: isEnabled)
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            SwiftUI.Text(label)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))

            TextField(placeholder, text: $value)
                .textFieldStyle(.plain)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
                .padding(.horizontal, Spacing.snug.points)
                .padding(.vertical, Spacing.snug.points)
                .background(appearance.swiftUI(SurfaceRole.well), in: shape)
                .overlay(shape.strokeBorder(appearance.swiftUI(outline), lineWidth: problem == nil ? 1 : 2))
                .focused($isFocused)
                .disabled(!isEnabled)
                .opacity(state == .disabled ? 0.45 : 1)
                .onHover { isHovering = $0 }

            if let problem {
                SwiftUI.Text(problem)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.critical))
            }
        }
        .animation(Motion.control.animation(appearance), value: problem)
        .animation(Motion.control.animation(appearance), value: state)
    }

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
    }

    private var outline: LineRole {
        if problem != nil { return .critical }
        switch state {
        case .focused: return .focusRing
        // Hover strengthens the outline rather than filling the field. A field is already
        // a well; lightening it on hover would make it look less inset the moment the
        // pointer arrives.
        case .hover: return .borderStrong
        default: return .border
        }
    }
}
