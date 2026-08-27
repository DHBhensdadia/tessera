import SwiftUI

/// One thing chosen from a list of things that exist.
///
/// `Chooser` rather than `Picker`, which SwiftUI owns — the rule that produced `TextRole`
/// and `ActionButton`, enforced by `NamingTests`.
///
/// Optional by construction: a room may have no building and an instructor no department.
/// A control that cannot express "none" is how somebody ends up inventing a building called
/// "None" that then appears in every printed timetable.
public struct Chooser: View {
    public struct Option: Identifiable, Hashable, Sendable {
        public let id: Int
        public let name: String

        public init(id: Int, name: String) {
            self.id = id
            self.name = name
        }
    }

    private let label: String
    private let options: [Option]
    private let emptyHint: String
    private let appearance: Appearance
    @Binding private var selection: Int?

    public init(
        label: String,
        options: [Option],
        selection: Binding<Int?>,
        emptyHint: String = "",
        appearance: Appearance
    ) {
        self.label = label
        self.options = options
        self._selection = selection
        self.emptyHint = emptyHint
        self.appearance = appearance
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            // An empty label takes no line. A caller inside a table row has already named
            // the thing in a column of its own, and a blank caption above every control
            // turned each row into two — visible the moment the mapping table was drawn.
            if !label.isEmpty {
                SwiftUI.Text(label)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            }

            if options.isEmpty {
                // Not a disabled menu. An empty menu says nothing about why it is empty or
                // what to do; this says both, and each of these lists has a screen of its
                // own that fills it.
                SwiftUI.Text(emptyHint)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    .padding(.vertical, Spacing.snug.points)
            } else {
                SwiftUI.Picker("", selection: $selection) {
                    SwiftUI.Text("None").tag(Int?.none)
                    ForEach(options) { option in
                        SwiftUI.Text(option.name).tag(Int?.some(option.id))
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .frame(maxWidth: 320, alignment: .leading)
            }
        }
    }
}

/// Several things chosen from a list of things that exist.
///
/// Checkboxes rather than a multi-select menu: a room's features are read far more often
/// than they are changed, and a closed menu reading "3 selected" hides the answer to the
/// question the screen exists to answer.
public struct MultiChooser: View {
    private let label: String
    private let options: [Chooser.Option]
    private let emptyHint: String
    private let appearance: Appearance
    @Binding private var selection: Set<Int>

    public init(
        label: String,
        options: [Chooser.Option],
        selection: Binding<Set<Int>>,
        emptyHint: String = "",
        appearance: Appearance
    ) {
        self.label = label
        self.options = options
        self._selection = selection
        self.emptyHint = emptyHint
        self.appearance = appearance
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            SwiftUI.Text(label)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))

            if options.isEmpty {
                SwiftUI.Text(emptyHint)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    .padding(.vertical, Spacing.snug.points)
            } else {
                VStack(alignment: .leading, spacing: Spacing.tight.points) {
                    ForEach(options) { option in
                        Toggle(
                            option.name,
                            isOn: Binding(
                                get: { selection.contains(option.id) },
                                set: { on in
                                    if on {
                                        selection.insert(option.id)
                                    } else {
                                        selection.remove(option.id)
                                    }
                                }
                            )
                        )
                        .toggleStyle(.checkbox)
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.primary))
                    }
                }
            }
        }
    }
}
