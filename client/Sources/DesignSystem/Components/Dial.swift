import SwiftUI

/// A whole number chosen from a small range, with a word for what it currently means.
///
/// Named `Dial` because `Slider` is SwiftUI's and the naming guard forbids shadowing it —
/// the same reason `Chooser` is not `Picker`.
///
/// The word and the number are shown **together**, deliberately. P7 draws these as
/// low/medium/high and that is the right register for somebody balancing a timetable rather
/// than tuning a solver — but a label with no number underneath it is untunable, and anybody
/// who cares enough to move eight of them eventually wants to know that "high" is 8. Showing
/// only the number is the opposite failure: 7 means nothing until you know the range.
///
/// The caller supplies the word. What a value *means* is the application's business, not the
/// design system's, and a control that knew about constraint weights would be a control that
/// only fits one screen.
public struct Dial: View {
    private let label: String
    @Binding private var value: Int
    private let range: ClosedRange<Int>
    private let caption: String
    private let appearance: Appearance

    public init(
        label: String,
        value: Binding<Int>,
        in range: ClosedRange<Int>,
        caption: String,
        appearance: Appearance
    ) {
        self.label = label
        _value = value
        self.range = range
        self.caption = caption
        self.appearance = appearance
    }

    private var binding: Binding<Double> {
        Binding(
            get: { Double(value) },
            // Rounded rather than truncated. A slider dragged to 6.97 is somebody aiming at
            // 7, and `Int(6.97)` is 6 — an off-by-one that appears only under the pointer
            // and never in a test that sets the value directly.
            set: { value = min(range.upperBound, max(range.lowerBound, Int($0.rounded()))) }
        )
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            HStack(alignment: .firstTextBaseline, spacing: Spacing.snug.points) {
                SwiftUI.Text(label)
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                Spacer(minLength: Spacing.regular.points)
                SwiftUI.Text(caption)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                SwiftUI.Text("\(value)")
                    .font(Typography.data.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    // Monospaced digits and a fixed width, so eight of these stacked do not
                    // shuffle sideways as the numbers change.
                    .frame(width: 20, alignment: .trailing)
            }
            SwiftUI.Slider(
                value: binding,
                in: Double(range.lowerBound)...Double(range.upperBound),
                step: 1
            )
            .controlSize(.small)
            .tint(appearance.swiftUI(SurfaceRole.accent))
        }
    }
}
