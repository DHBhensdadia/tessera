import DesignSystem
import EngineClient
import SwiftUI

/// What the solver must do, and what it should prefer.
///
/// P7 Act 5 splits this screen in three, and the split is the teaching:
///
/// > The split between "always enforced" (visible, explained, immutable) and "preferences"
/// > (sliders) teaches the hard/soft distinction without a tutorial. And when the solver
/// > later produces something you dislike, the fix is a slider — not an argument with the
/// > algorithm.
///
/// Not a list-and-inspector. `EntityWorkspace` is right for eleven screens and wrong for
/// this one: there is nothing to search, the invariants cannot be selected because they
/// cannot be edited, and a preference's whole interface is one control — putting it behind
/// a selection would hide eight sliders behind eight clicks.
struct ConstraintsScreen: View {
    let term: Int?
    let appearance: Appearance

    @State private var store: ConstraintStore?

    init(connection: EngineConnection, term: Int?, appearance: Appearance) {
        self.term = term
        self.appearance = appearance
        _store = State(
            initialValue: term.map { ConstraintStore(connection: connection, term: $0) }
        )
    }

    /// A screen around a store that has already loaded.
    ///
    /// For `--render`. `ImageRenderer` draws into a bitmap with no run loop, so `.task`
    /// never fires and a screen that loads itself renders its empty state. Handing it a
    /// filled store is the difference between a picture of this screen and a picture of the
    /// sentence that says no term is chosen.
    init(loaded store: ConstraintStore, appearance: Appearance) {
        self.term = 0
        self.appearance = appearance
        _store = State(initialValue: store)
    }

    var body: some View {
        ScrollView { content }
            .task { await store?.load() }
    }

    /// The blocks, outside the scroll container.
    ///
    /// Exposed because `--render` draws this screen offscreen, and `ImageRenderer` renders a
    /// `ScrollView` as **nothing** — the same class of limit as `glassEffect`, and found the
    /// same way: a render that reported success and produced a picture of the background
    /// colour.
    ///
    /// It is the honest shape anyway. A `ScrollView` is how a screen taller than its window
    /// is made reachable; it is not part of what the screen *is*. Drawn at full height, all
    /// three blocks are one picture — which is what this screen needs, since the third was
    /// never once photographed while it lived below the fold of a display.
    @ViewBuilder
    var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let store {
                if let notice = store.notice {
                    NoticeBar(text: notice, appearance: appearance) { store.notice = nil }
                }
                AlwaysEnforced(invariants: store.invariants, appearance: appearance)
                Preferences(store: store, appearance: appearance)
                CustomRules(store: store, appearance: appearance)
            } else {
                ContentSection("Rules", showsRule: false, appearance: appearance) {
                    Text("Rules belong to a term, because the same department may want "
                         + "them balanced differently from one semester to the next. "
                         + "Choose a term in the toolbar.")
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The rules that cannot be switched off.
///
/// Every sentence comes from the engine. Writing them here would put the authoritative
/// statement of Tessera's hard rules in the client, where the solver cannot see it and 4.1
/// would have to duplicate it.
private struct AlwaysEnforced: View {
    let invariants: [ConstraintStore.Invariant]
    let appearance: Appearance

    var body: some View {
        ContentSection("Always enforced", appearance: appearance) {
            ForEach(invariants) { invariant in
                HStack(alignment: .firstTextBaseline, spacing: Spacing.regular.points) {
                    Image(systemName: "checkmark")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.positive))
                        .frame(width: 14)
                    VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                        Text(invariant.statement)
                            .font(Typography.body.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.primary))
                        Text(invariant.because)
                            .font(Typography.caption.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    }
                }
                .padding(.vertical, Spacing.tight.points)
            }
            Text("These cannot be disabled. A timetable violating one is not a worse "
                 + "timetable — it is an invalid one.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                .padding(.top, Spacing.snug.points)
        }
    }
}

/// The weighted preferences, as sliders.
private struct Preferences: View {
    let store: ConstraintStore
    let appearance: Appearance

    var body: some View {
        ContentSection("Preferences", appearance: appearance) {
            if store.preferences.isEmpty {
                Text("This term has no preferences set. A new term starts with seven.")
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            } else {
                Text("What the solver should aim for when it cannot satisfy everything. "
                     + "Higher means a violation costs more.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    .padding(.bottom, Spacing.snug.points)

                ForEach(store.preferences) { preference in
                    PreferenceRow(preference: preference, store: store, appearance: appearance)
                    if preference.id != store.preferences.last?.id {
                        Rule(appearance: appearance)
                            .padding(.vertical, Spacing.snug.points)
                    }
                }
            }
        }
    }
}

private struct PreferenceRow: View {
    let preference: ConstraintStore.Preference
    let store: ConstraintStore
    let appearance: Appearance

    private var weight: Binding<Int> {
        Binding(
            get: { preference.weight },
            set: { new in
                guard new != preference.weight else { return }
                Task { await store.setWeight(new, on: preference) }
            }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            Dial(
                label: preference.summary,
                value: weight,
                in: WeightScale.range,
                caption: WeightScale.caption(for: preference.weight),
                appearance: appearance
            )
            .disabled(!preference.enabled)
            .opacity(preference.enabled ? 1 : 0.5)

            HStack(spacing: Spacing.snug.points) {
                // Disabling is not deleting and not a weight of zero. Kept as its own
                // control because the model keeps it as its own field, and collapsing the
                // three would be simpler and would lie.
                SwiftUI.Toggle(
                    preference.enabled ? "Considered" : "Ignored",
                    isOn: Binding(
                        get: { preference.enabled },
                        set: { wanted in
                            Task { await store.setEnabled(wanted, on: preference) }
                        }
                    )
                )
                .toggleStyle(.checkbox)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))

                if preference.narrowedTo > 0 {
                    // A global kind that names targets is that preference narrowed. Saying
                    // "everyone" when it means three people would be the worst kind of
                    // wrong on this screen: quietly reassuring.
                    Badge(
                        "\(preference.narrowedTo) named",
                        tone: .info,
                        appearance: appearance
                    )
                }
            }
        }
    }
}
