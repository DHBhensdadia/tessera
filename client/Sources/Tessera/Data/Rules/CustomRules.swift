import DesignSystem
import EngineClient
import SwiftUI

/// The third block: rules somebody wrote, and the form that writes them.
struct CustomRules: View {
    let store: ConstraintStore
    let appearance: Appearance

    @State private var isAdding = false

    var body: some View {
        ContentSection("Custom rules", showsRule: false, appearance: appearance) {
            if store.customRules.isEmpty && !isAdding {
                Text("Nothing beyond the preferences above. A custom rule names who or what "
                     + "it applies to — one instructor, two sessions, a course.")
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            }

            ForEach(store.customRules) { rule in
                HStack(alignment: .firstTextBaseline, spacing: Spacing.regular.points) {
                    VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                        Text(rule.summary)
                            .font(Typography.body.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.primary))
                        if !rule.enabled {
                            Text("Not considered")
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                        }
                    }
                    Spacer(minLength: Spacing.snug.points)
                    // Hard and soft are the distinction the whole screen teaches, so a rule
                    // says which it is rather than leaving it to be inferred from a weight.
                    Badge(
                        rule.isHard ? "hard" : "soft · \(WeightScale.word(for: rule.weight))",
                        tone: rule.isHard ? .warning : .neutral,
                        appearance: appearance
                    )
                    ActionButton(emphasis: .destructive, appearance: appearance) {
                        Task { await store.delete(rule) }
                    } label: {
                        Text("Remove")
                    }
                }
                .padding(.vertical, Spacing.snug.points)
                if rule.id != store.customRules.last?.id {
                    Rule(appearance: appearance)
                }
            }

            if isAdding {
                RuleForm(store: store, appearance: appearance) { isAdding = false }
                    .padding(.top, Spacing.regular.points)
            } else {
                ActionButton(appearance: appearance, action: { isAdding = true }) {
                    Text("Add rule…")
                }
                .padding(.top, Spacing.regular.points)
            }
        }
    }
}

/// A form that assembles itself from whatever the catalogue says about the chosen kind.
///
/// D5: sixteen kinds, and sixteen hand-written forms would be sixteen places to update when
/// a seventeenth arrives — which is the exact promise Decision #12 made. So the kind decides
/// what is on screen: which target kinds may be named, which parameters exist and what their
/// bounds are, and the sentence that says what all of it means.
struct RuleForm: View {
    let store: ConstraintStore
    let appearance: Appearance
    let done: () -> Void

    @State private var kindID: Int?
    @State private var targetKindID: Int?
    @State private var selected: Set<Int> = []
    @State private var params: [String: String] = [:]
    @State private var isHard = false
    @State private var weight = 5
    @State private var options: [Chooser.Option] = []

    private var kind: Components.Schemas.ConstraintKindRead? {
        kindID.flatMap { id in store.kinds.indices.contains(id) ? store.kinds[id] : nil }
    }

    /// Which target kinds this rule may name. Several kinds permit more than one — a rule
    /// about building changes applies to groups *or* instructors — so the form asks.
    private var targetKinds: [Components.Schemas.TargetKind] { kind?.targets ?? [] }

    private var targetKind: Components.Schemas.TargetKind? {
        guard !targetKinds.isEmpty else { return nil }
        guard let targetKindID, targetKinds.indices.contains(targetKindID) else {
            return targetKinds.first
        }
        return targetKinds[targetKindID]
    }

    private var numbers: [String: Int] {
        var values: [String: Int] = [:]
        for spec in kind?.params ?? [] {
            if case .success(let value) = NumberEntry.count(params[spec.name] ?? "") {
                values[spec.name] = value
            }
        }
        return values
    }

    /// The sentence, as it stands.
    private var sentence: String {
        guard let kind else { return "" }
        let names = options.filter { selected.contains($0.id) }.map(\.name)
        return RuleSentence.render(
            template: kind.summary_template,
            params: numbers,
            targets: names,
            unnarrowed: kind.unnarrowed
        )
    }

    private var missing: [String] {
        guard let kind else { return [] }
        return RuleSentence.unfilled(template: kind.summary_template, params: numbers)
    }

    /// A targeted rule is meaningless without targets, and only a rule that names them may
    /// be hard — both facts the engine states, mirrored here so Create is not a guess.
    private var isComplete: Bool {
        guard let kind else { return false }
        guard missing.isEmpty else { return false }
        if kind.scope == .targeted { return !selected.isEmpty }
        return true
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.regular.points) {
            Chooser(
                label: "Rule",
                options: store.kinds.enumerated().map { .init(id: $0.offset, name: $0.element.example) },
                selection: $kindID,
                emptyHint: "The engine published no rules, which should not happen.",
                appearance: appearance
            )

            if let kind {
                if targetKinds.count > 1 {
                    Chooser(
                        label: "Applies to",
                        options: targetKinds.enumerated().map {
                            .init(id: $0.offset, name: $0.element.rawValue.capitalized + "s")
                        },
                        selection: $targetKindID,
                        emptyHint: "",
                        appearance: appearance
                    )
                }

                targets(for: kind)

                ForEach(kind.params ?? [], id: \.name) { spec in
                    Field(
                        label: spec.label,
                        placeholder: String(spec._default),
                        value: Binding(
                            get: { params[spec.name] ?? String(spec._default) },
                            set: { params[spec.name] = $0 }
                        ),
                        problem: outOfRange(spec),
                        appearance: appearance
                    )
                    .frame(maxWidth: 220)
                }

                strength(kind)

                // The feature. Live, because a form of five controls and a Create button is
                // otherwise something you find out about afterwards.
                Text(sentence)
                    .font(Typography.body.font.italic())
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                    .padding(.vertical, Spacing.snug.points)

                if let notice = store.message(for: "params") ?? store.message(for: "targets") {
                    Text(notice)
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.critical))
                }
            }

            HStack(spacing: Spacing.regular.points) {
                ActionButton(
                    emphasis: .primary,
                    appearance: appearance,
                    action: { Task { await create() } }
                ) {
                    Text("Create")
                }
                .disabled(!isComplete)
                ActionButton(appearance: appearance, action: done) { Text("Cancel") }
            }
        }
        .task(id: targetKind?.rawValue) {
            selected = []
            if let targetKind {
                options = await store.options(for: targetKind)
            } else {
                options = []
            }
        }
    }

    @ViewBuilder
    private func targets(for kind: Components.Schemas.ConstraintKindRead) -> some View {
        if targetKind == .session && options.isEmpty {
            // D6. A targeted rule needs sessions, and sessions do not exist until an
            // offering has been expanded — so the form says the thing to go and do rather
            // than showing an empty picker and letting somebody wonder.
            Text("This rule applies to sessions, and this term has none yet. Expand an "
                 + "offering's weekly pattern first, and its sessions appear here.")
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
        } else {
            MultiChooser(
                label: kind.scope == .targeted ? "Which ones" : "Only for",
                options: options,
                selection: $selected,
                emptyHint: "Nothing to name yet.",
                appearance: appearance
            )
            if kind.scope == .global && selected.isEmpty {
                Text("Naming nobody makes this apply to \(kind.unnarrowed).")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
        }
    }

    /// Hard or soft, and a weight only when the answer is soft.
    ///
    /// The weight control disappears rather than greys out, because `effective_weight` is 0
    /// for a hard constraint: a weight on a hard rule is not a disabled setting, it is a
    /// meaningless one.
    @ViewBuilder
    private func strength(_ kind: Components.Schemas.ConstraintKindRead) -> some View {
        if selected.isEmpty {
            Text("A rule that names nobody is a preference, so it is weighed rather than "
                 + "enforced.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        } else {
            SwiftUI.Toggle("Must hold — refuse any timetable that breaks it", isOn: $isHard)
                .toggleStyle(.checkbox)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
        }
        if !isHard || selected.isEmpty {
            Dial(
                label: "How strongly",
                value: $weight,
                in: WeightScale.range,
                caption: WeightScale.caption(for: weight),
                appearance: appearance
            )
        }
    }

    private func outOfRange(_ spec: Components.Schemas.ParamRead) -> String? {
        guard let value = numbers[spec.name] else { return nil }
        guard value < spec.minimum || value > spec.maximum else { return nil }
        return "must be between \(spec.minimum) and \(spec.maximum)"
    }

    private func create() async {
        guard let kind, let targetKind else { return }
        let targets = selected.map { Components.Schemas.TargetWire(id: $0, kind: targetKind) }
        let wrote = await store.create(
            kind: kind.kind,
            targets: targets,
            params: numbers,
            isHard: isHard && !selected.isEmpty,
            weight: weight
        )
        if wrote { done() }
    }
}
