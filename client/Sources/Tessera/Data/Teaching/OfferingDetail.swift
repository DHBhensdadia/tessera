import DesignSystem
import SwiftUI

/// One offering, and the weekly pattern it repeats.
///
/// P7 Act 5 draws this exactly:
///
///     3 × Lecture    60 min   whole batch    Prof. Sharma
///                    requires: projector
///     1 × Lab       120 min   per sub-batch  Prof. Sharma
///                    → generates 3 sessions (A1, A2, A3)
///     Total: 6 sessions per week
///
/// The "→ generates 3 sessions" line is doing the teaching: it is what makes the split
/// between a pattern and the sessions it produces visible without anybody reading
/// documentation, and it is why this screen shows counts the engine computed rather than
/// arithmetic done here.
struct OfferingDetail: View {
    let offering: OfferingStore.Offering
    let store: OfferingStore
    let appearance: Appearance

    @State private var draft = TemplateDraft()
    @State private var isComposing = false
    /// Which pattern line is open for editing, if any.
    ///
    /// One at a time, and none by default. Every line carrying its own controls inline made
    /// the pattern a column of forms: two lines pushed the total and the Expand button off
    /// the bottom of the window, which are the two things somebody actually came here to
    /// see. P7 draws this as a compact table for the same reason.
    @State private var editing: Int?

    /// What the pattern means, which is what P7's mock states and what somebody is
    /// deciding when they edit it. Deliberately not the number of sessions that exist —
    /// those are reported below, where the difference between the two is the point.
    private var totalPerWeek: Int {
        offering.templates.reduce(0) { $0 + $1.wanted }
    }

    private var isStale: Bool {
        offering.templates.contains { $0.isStale }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Offering", appearance: appearance) {
                Text(store.label(for: offering))
                    .font(Typography.title.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                Text("A course is offered once per term, and which course cannot be changed afterwards.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }

            ContentSection("Weekly pattern", appearance: appearance) {
                if offering.templates.isEmpty {
                    Text("Nothing yet. A pattern says how often this is taught, for how long, and to whom.")
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                } else {
                    ForEach(offering.templates) { template in
                        TemplateRow(
                            template: template,
                            offering: offering.id,
                            store: store,
                            isEditing: editing == template.id,
                            toggle: { editing = editing == template.id ? nil : template.id },
                            appearance: appearance
                        )
                    }
                    Text(totalPerWeek == 1
                         ? "Total: 1 session per week"
                         : "Total: \(totalPerWeek) sessions per week")
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.primary))
                }

                if isComposing {
                    TemplateComposer(
                        draft: $draft,
                        store: store,
                        appearance: appearance,
                        cancel: { isComposing = false },
                        commit: {
                            let ready = draft
                            isComposing = false
                            draft = TemplateDraft()
                            Task { await store.addTemplate(to: offering.id, ready) }
                        }
                    )
                } else {
                    ActionButton(appearance: appearance) { isComposing = true } label: {
                        Text("Add a pattern")
                    }
                }
            }

            ContentSection("Sessions", showsRule: false, appearance: appearance) {
                Text("Expanding turns the pattern above into the sessions the solver places. "
                     + "It adds what is missing and leaves anything already scheduled alone.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))

                HStack(spacing: Spacing.regular.points) {
                    ActionButton(
                        emphasis: .primary,
                        enabled: !offering.templates.isEmpty,
                        appearance: appearance
                    ) {
                        Task { await store.expand(offering) }
                    } label: {
                        Text("Expand into sessions")
                    }

                    if let said = store.lastExpansion {
                        Text(said)
                            .font(Typography.body.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    } else if isStale {
                        // The pattern and the sessions disagree, which is the normal state
                        // after an edit and the reason expanding is a button rather than
                        // something that happens invisibly.
                        Text(offering.sessionCount == 0
                             ? "None generated yet."
                             : "\(offering.sessionCount) generated, \(totalPerWeek) wanted.")
                            .font(Typography.body.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    } else if offering.sessionCount > 0 {
                        Text("\(offering.sessionCount) generated, and up to date.")
                            .font(Typography.body.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    }
                }
            }
        }
        .task(id: offering.id) {
            isComposing = false
            editing = nil
            draft = TemplateDraft()
        }
    }
}

/// One line of the pattern: what it is, and the two things about it that can change.
private struct TemplateRow: View {
    let template: OfferingStore.Template
    let offering: Int
    let store: OfferingStore
    let isEditing: Bool
    let toggle: () -> Void
    let appearance: Appearance

    @State private var perWeek = ""
    @State private var split = false
    @State private var attendees: Set<Int> = []

    /// The headline, in P7's words: `3 × Lecture · 60 min · whole batch`.
    private var headline: String {
        let audience = template.splitPerAttendee ? "per sub-batch" : "whole batch"
        return "\(template.perWeek) × \(template.kind.capitalized) · "
            + "\(store.minutes(template.durationSlots)) min · \(audience)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            summary
            if isEditing { controls }
            Rule(appearance: appearance)
        }
        // Keyed on the template *and* on whether the row is open: closing and reopening
        // must show what the engine holds, not what was half-typed before.
        .task(id: "\(template.id)-\(isEditing)") {
            perWeek = String(template.perWeek)
            split = template.splitPerAttendee
            attendees = template.attendeeIDs
        }
    }

    /// What P7's table shows, and all it shows: the shape, who teaches it, what it needs,
    /// and — the line doing the teaching — how many sessions it comes to.
    private var summary: some View {
        Button(action: toggle) {
            VStack(alignment: .leading, spacing: Spacing.tight.points) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.snug.points) {
                    Text(headline)
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.primary))
                    Spacer(minLength: Spacing.snug.points)
                    Text(isEditing ? "Done" : "Edit")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.info))
                }
                if !template.instructorNames.isEmpty {
                    Text(template.instructorNames.joined(separator: ", "))
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }
                if !template.featureNames.isEmpty {
                    Text("requires: \(template.featureNames.joined(separator: ", "))")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }
                // Only worth saying when the pattern produces more than the one session a
                // reader would already assume from the count in front of them.
                if template.wanted > template.perWeek, !template.attendeeNames.isEmpty {
                    Text("→ generates \(template.wanted) sessions "
                         + "(\(template.attendeeNames.joined(separator: ", ")))")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    /// The two things about a pattern that can change, and a plain sentence about the rest.
    @ViewBuilder
    private var controls: some View {
        Field(
            label: "Times per week",
            placeholder: "3",
            value: $perWeek,
            problem: store.problem(for: "per_week"),
            appearance: appearance
        )
        .onSubmit(commit)
        .frame(maxWidth: 160)

        Toggle("One session per group", isOn: $split)
            .toggleStyle(.checkbox)
            .font(Typography.body.font)
            .foregroundStyle(appearance.swiftUI(TextRole.primary))
            .onChange(of: split) { commit() }

        MultiChooser(
            label: "Attends",
            options: store.groups,
            selection: $attendees,
            emptyHint: "No student groups yet — add some under Data first.",
            appearance: appearance
        )
        .onChange(of: attendees) { commit() }

        Text("Its length, kind, instructors and required features are fixed. "
             + "To change those, remove this line and add it again.")
            .font(Typography.caption.font)
            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))

        ActionButton(emphasis: .destructive, appearance: appearance) {
            Task { await store.deleteTemplate(template, in: offering) }
        } label: {
            Text("Remove this line")
        }
    }

    private func commit() {
        var edited = template
        edited.splitPerAttendee = split
        edited.attendeeIDs = attendees
        switch NumberEntry.count(perWeek) {
        case .success(let value):
            store.complain(nil, about: "per_week")
            edited.perWeek = value
        case .failure(let complaint):
            store.complain(complaint.message, about: "per_week")
            return
        }
        Task { await store.saveTemplate(edited, in: offering) }
    }
}

/// A new pattern line, composed before it exists.
private struct TemplateComposer: View {
    @Binding var draft: TemplateDraft
    let store: OfferingStore
    let appearance: Appearance
    let cancel: () -> Void
    let commit: () -> Void

    @State private var duration = "1"
    @State private var perWeek = "1"
    @State private var kind: Int? = 0

    private var kindOptions: [Chooser.Option] {
        TemplateDraft.kinds.enumerated().map { .init(id: $0.offset, name: $0.element.capitalized) }
    }

    /// The engine refuses a pattern with no attendees, so the button says so first.
    private var isReady: Bool { !draft.attendeeIDs.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.regular.points) {
            Text("New pattern")
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))

            Chooser(
                label: "Kind",
                options: kindOptions,
                selection: $kind,
                appearance: appearance
            )

            Field(label: "Times per week", placeholder: "3", value: $perWeek, appearance: appearance)
                .frame(maxWidth: 160)

            Field(
                label: "Length, in slots of \(store.slotMinutes) min",
                placeholder: "2",
                value: $duration,
                appearance: appearance
            )
            .frame(maxWidth: 220)

            Toggle("One session per group", isOn: $draft.splitPerAttendee)
                .toggleStyle(.checkbox)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))

            MultiChooser(
                label: "Attends",
                options: store.groups,
                selection: $draft.attendeeIDs,
                emptyHint: "No student groups yet — a pattern needs at least one.",
                appearance: appearance
            )

            MultiChooser(
                label: "Taught by",
                options: store.instructors,
                selection: $draft.instructorIDs,
                emptyHint: "No instructors yet.",
                appearance: appearance
            )

            MultiChooser(
                label: "Requires",
                options: store.features,
                selection: $draft.featureIDs,
                emptyHint: "No room features yet.",
                appearance: appearance
            )

            HStack(spacing: Spacing.regular.points) {
                ActionButton(emphasis: .primary, enabled: isReady, appearance: appearance) {
                    draft.kind = TemplateDraft.kinds[kind ?? 0]
                    if case .success(let value) = NumberEntry.count(perWeek) { draft.perWeek = value }
                    if case .success(let value) = NumberEntry.count(duration) { draft.durationSlots = value }
                    commit()
                } label: {
                    Text("Add pattern")
                }
                ActionButton(appearance: appearance, action: cancel) { Text("Cancel") }
                if !isReady {
                    Text("Choose who attends first.")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                }
            }
        }
        .padding(.vertical, Spacing.snug.points)
    }
}
