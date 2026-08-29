import DesignSystem
import SwiftUI

/// The shape every data screen in the application has: a list, and the selected item.
///
/// P7 Act 5: *"Every data section uses the same list + inspector pattern, so learning one
/// teaches all of them."* Built once rather than eight times, and the split is where the
/// entities genuinely agree — a searchable list, a selection, an add button, a delete that
/// can be refused, and somewhere for a message that belongs to no field. What an item *is*
/// lives entirely in the detail view.
///
/// The risk of a generic container is the familiar one: an abstraction that fits the first
/// screen and fights the fifth. So this one is deliberately thin — it owns no field, no
/// relationship and no validation — and it is proven against Rooms before seven more
/// screens are built on it.
struct EntityWorkspace<Item: Identifiable, Detail: View>: View {
    let title: String
    let items: [Item]
    let label: (Item) -> String
    /// The one figure worth seeing without opening an item — a capacity, a headcount, a
    /// credit count. P7's mocks show one in every list, and a list of bare names makes a
    /// person open each row to compare them.
    let value: (Item) -> String?
    let detail: (Item) -> Detail
    /// Where an item sits in a hierarchy, when the entity has one.
    ///
    /// Only student groups do. Rather than a second container for the one shape that is not
    /// a flat list, the list *is* the tree, flattened in the order it should read, and each
    /// item says how deep it is and whether it can be opened. Search then keeps working
    /// unchanged — a match five levels down is still a match — which a bespoke outline
    /// would have had to re-solve.
    /// `var` with a default rather than `let`, because Swift's memberwise initialiser only
    /// supplies a default for a property that can be reassigned. Eight screens are flat and
    /// should not each have to say so.
    var nesting: (Item) -> Row.Nesting? = { _ in nil }
    var toggle: (Item) -> Void = { _ in }
    let adding: Adding
    let delete: (Item) -> Void

    /// How a new one comes into being, which is not the same question for every entity.
    ///
    /// Most things here are a name you type afterwards: Add makes a blank one, selects it,
    /// and the inspector is where it becomes real. An **offering** is not. An offering *is*
    /// a course being taught in a term — there is no `PATCH /offerings`, and its course is
    /// fixed the moment it exists — so "Add" with nothing chosen would have to guess, and
    /// the guess would be permanent.
    ///
    /// Naming the two cases rather than adding a flag, because they are different
    /// interactions and a container that accepted both an action *and* a list of choices
    /// would have a meaningless third state.
    enum Adding {
        /// Add makes a blank one to be edited afterwards.
        case blank(() -> Void)
        /// Add asks which, because the answer cannot be changed afterwards.
        case choosing(from: [Chooser.Option], empty: String, choose: (Int) -> Void)
    }

    /// What deleting one of these actually does, in the entity's own terms.
    ///
    /// Not one sentence for everything. The container originally promised *"if anything
    /// still depends on it, Tessera will refuse and say what"* — which is true of student
    /// groups (#48) and **false of buildings**, where `room.building_id` is ON DELETE SET
    /// NULL by deliberate design: losing a hundred rooms because a building was deleted
    /// would be far worse than a hundred rooms briefly lacking an address. A dialog that
    /// promises a refusal and then silently detaches things is worse than no dialog.
    let deleteWarning: String

    @Binding var selection: Item.ID?
    /// A refusal that belongs to no particular field — a rule violation, or a complaint
    /// about a field this form does not have. Never swallowed.
    let notice: String?
    let dismissNotice: () -> Void

    let appearance: Appearance
    @State private var search = ""
    @State private var confirmingDelete: Item.ID?

    var body: some View {
        HStack(spacing: 0) {
            // Pinned to the top rather than centred. In a window the list fills the height
            // on its own and this changes nothing; drawn offscreen at full height it is the
            // difference between a list at the top of its column and one floating in the
            // middle of it, beside an inspector three times as tall.
            list.frame(maxHeight: .infinity, alignment: .top)
            Rectangle()
                .fill(appearance.swiftUI(LineRole.border))
                .frame(width: 1)
            inspector
        }
    }

    private var shown: [Item] {
        let query = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !query.isEmpty else { return items }
        return items.filter { label($0).lowercased().contains(query) }
    }

    private var selected: Item? {
        items.first { $0.id == selection }
    }

    // MARK: - The list

    private var list: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: Spacing.snug.points) {
                Field(
                    label: "",
                    placeholder: "Search \(title.lowercased())",
                    value: $search,
                    appearance: appearance
                )
                addControl
            }
            .padding(Spacing.regular.points)

            Rule(appearance: appearance)

            if items.isEmpty {
                Spacer()
                EmptyState(
                    symbol: "tray",
                    title: "No \(title.lowercased()) yet",
                    explanation: "Add the first one, or import a spreadsheet.",
                    appearance: appearance
                )
                Spacer()
            } else {
                ScrollsInAWindow {
                    VStack(spacing: 0) {
                        ForEach(shown) { item in
                            Row(
                                label(item),
                                value: value(item),
                                isSelected: item.id == selection,
                                nesting: nesting(item),
                                appearance: appearance,
                                select: { selection = item.id },
                                toggle: { toggle(item) }
                            )
                        }
                        if shown.isEmpty {
                            Text("Nothing matches “\(search)”.")
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                                .padding(Spacing.loose.points)
                        }
                    }
                }
            }
        }
        .frame(width: 340)
        .background(appearance.swiftUI(SurfaceRole.base))
    }


    /// Add, in whichever of its two forms this entity has.
    @ViewBuilder
    private var addControl: some View {
        switch adding {
        case .blank(let act):
            ActionButton(emphasis: .primary, appearance: appearance, action: act) {
                Text("Add")
            }
        case .choosing(let options, let empty, let choose):
            Menu {
                if options.isEmpty {
                    // A disabled menu item rather than an empty menu: an empty menu says
                    // nothing about why it is empty, and this is the moment a person most
                    // needs to be told what to do first.
                    Button(empty) {}.disabled(true)
                } else {
                    ForEach(options) { option in
                        Button(option.name) { choose(option.id) }
                    }
                }
            } label: {
                Text("Add")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
    }

    // MARK: - The inspector

    @ViewBuilder
    private var inspector: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let notice {
                NoticeBar(text: notice, appearance: appearance, dismiss: dismissNotice)
            }
            if let selected {
                ScrollsInAWindow {
                    VStack(alignment: .leading, spacing: 0) {
                        detail(selected)
                        ContentSection(showsRule: false, appearance: appearance) {
                            ActionButton(emphasis: .destructive, appearance: appearance) {
                                confirmingDelete = selected.id
                            } label: {
                                Text("Delete \(label(selected))")
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Spacer()
                EmptyState(
                    symbol: "sidebar.right",
                    title: "Nothing selected",
                    explanation: "Choose something on the left to see and edit its details.",
                    appearance: appearance
                )
                Spacer()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(appearance.swiftUI(SurfaceRole.base))
        .confirmationDialog(
            "Delete this permanently?",
            isPresented: Binding(get: { confirmingDelete != nil }, set: { if !$0 { confirmingDelete = nil } })
        ) {
            Button("Delete", role: .destructive) {
                if let id = confirmingDelete, let item = items.first(where: { $0.id == id }) {
                    delete(item)
                }
                confirmingDelete = nil
            }
            Button("Cancel", role: .cancel) { confirmingDelete = nil }
        } message: {
            Text(deleteWarning)
        }
    }
}

/// Where a refusal goes when it belongs to no field.
///
/// Dismissible but not automatic: a message that fades on a timer is one somebody misses
/// while reading the form it is about.
struct NoticeBar: View {
    let text: String
    let appearance: Appearance
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.regular.points) {
            Image(systemName: "exclamationmark.triangle")
                .foregroundStyle(appearance.swiftUI(TextRole.critical))
            Text(text)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Spacing.snug.points)
            Button("Dismiss", action: dismiss)
                .buttonStyle(.plain)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
        }
        .padding(Spacing.regular.points)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(appearance.swiftUI(SurfaceRole.well))
        .overlay(alignment: .bottom) { Rule(appearance: appearance) }
    }
}
