import SwiftUI

/// A hairline that divides a plane.
///
/// `Rule` rather than `Divider`: SwiftUI owns that name, and its divider draws the
/// system's separator colour rather than ours, which is one shade off in both schemes.
///
/// The typographic term is the right one — this is a rule in the sense a printed page has
/// rules, and it is the load-bearing structural device in this design system now that
/// nothing is grouped by elevation.
public struct Rule: View {
    private let appearance: Appearance

    public init(appearance: Appearance) {
        self.appearance = appearance
    }

    public var body: some View {
        Rectangle()
            .fill(appearance.swiftUI(LineRole.border))
            .frame(height: 1)
            .frame(maxWidth: .infinity)
            .accessibilityHidden(true)
    }
}

/// The quiet label above a group.
///
/// Uppercase, tracked, tertiary. Six references put exactly this above every group and
/// none of them makes it loud: the label is there to be found when looked for, not to be
/// read on the way past.
public struct SectionLabel: View {
    private let text: String
    private let appearance: Appearance

    public init(_ text: String, appearance: Appearance) {
        self.text = text
        self.appearance = appearance
    }

    public var body: some View {
        SwiftUI.Text(text.uppercased())
            .font(Typography.caption.font)
            .tracking(0.8)
            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
    }
}

/// A titled group of content, closed by a rule.
///
/// **This is what replaced `Card`.** The card was a rounded rectangle with a fill and a
/// shadow, which is the single most recognisable signature of generated interface code and
/// an idiom not one of the seventeen references uses. A group is not an object; it does not
/// need edges. It needs a name and an end.
///
/// `ContentSection` rather than `Section`, which SwiftUI owns — the same rule that made
/// `TextRole` and `ActionButton`, and one the naming test enforces.
///
/// **The rule is full-bleed and the content is inset.** That is the whole difference
/// between a division of the surface and an underline beneath some text, and it means a
/// pane containing sections must not add horizontal padding of its own — the section owns
/// its inset so that every section in the application lines up.
public struct ContentSection<Content: View>: View {
    private let title: String?
    private let showsRule: Bool
    private let appearance: Appearance
    private let content: Content

    public init(
        _ title: String? = nil,
        showsRule: Bool = true,
        appearance: Appearance,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.showsRule = showsRule
        self.appearance = appearance
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: Spacing.regular.points) {
                if let title {
                    SectionLabel(title, appearance: appearance)
                }
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Spacing.page.points)
            .padding(.vertical, Spacing.section.points)

            if showsRule {
                Rule(appearance: appearance)
            }
        }
    }
}

/// A bounded object: a rail, a search field, a segmented control, an account switcher.
///
/// The one place a container is right, and the references agree on how to draw it — a
/// hairline stroke, a faint fill, a small radius, **and no shadow**. Nine of seventeen do
/// exactly this; none of them uses it to group content, which is what `ContentSection` is
/// for.
///
/// The distinction is worth holding on to. A `Panel` says *this is a thing*. A
/// `ContentSection` says *these belong together*. Drawing the second like the first is how
/// an interface ends up as a page of floating rectangles.
public struct Panel<Content: View>: View {
    private let isFilled: Bool
    private let appearance: Appearance
    private let content: Content

    public init(
        filled: Bool = true,
        appearance: Appearance,
        @ViewBuilder content: () -> Content
    ) {
        self.isFilled = filled
        self.appearance = appearance
        self.content = content()
    }

    public var body: some View {
        content
            .background {
                if isFilled {
                    shape.fill(appearance.swiftUI(SurfaceRole.panel))
                }
            }
            .overlay(shape.strokeBorder(appearance.swiftUI(LineRole.border), lineWidth: 1))
    }

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: Radius.container.points, style: .continuous)
    }
}
