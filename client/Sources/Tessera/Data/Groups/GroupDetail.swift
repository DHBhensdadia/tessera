import DesignSystem
import SwiftUI

/// One student group: what it is called, how many it holds, and where it sits.
struct GroupDetail: View {
    let group: GroupStore.Group
    let store: GroupStore
    let appearance: Appearance

    @State private var name = ""
    @State private var size = ""
    @State private var programID: Int?
    @State private var parentID: Int?
    @State private var memberIDs: Set<Int> = []
    @State private var batches = "3"
    @State private var isSplitting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection(group.isCohort ? "Elective" : "Group", appearance: appearance) {
                Field(
                    label: "Name",
                    placeholder: "2024 Intake — Semester 5",
                    value: $name,
                    problem: store.problem(for: "name"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Students",
                    placeholder: "120",
                    value: $size,
                    problem: store.problem(for: "size"),
                    appearance: appearance
                )
                .onSubmit(commit)

                if group.headcount != group.size {
                    Text("Counts as \(group.headcount) — the students in the groups below it.")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }

                Chooser(
                    label: "Programme",
                    options: store.programs,
                    selection: $programID,
                    emptyHint: "No programmes yet — add one under Setup first.",
                    appearance: appearance
                )
                .onChange(of: programID) { commit() }
            }

            if group.isCohort {
                ContentSection("Draws from", showsRule: false, appearance: appearance) {
                    Text("An elective takes students from other groups, so it has no place in "
                         + "the tree. Those groups cannot be scheduled against it.")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    MultiChooser(
                        label: "Groups",
                        options: store.memberOptions,
                        selection: $memberIDs,
                        emptyHint: "No other groups yet.",
                        appearance: appearance
                    )
                    .onChange(of: memberIDs) { commit() }
                }
            } else {
                ContentSection("Where it sits", appearance: appearance) {
                    Chooser(
                        label: "Inside",
                        options: store.parentOptions(for: group),
                        selection: $parentID,
                        emptyHint: "Nothing else to sit inside yet.",
                        appearance: appearance
                    )
                    .onChange(of: parentID) { commit() }

                    Text("Leave this as None to make it a root. Tessera refuses a move that "
                         + "would put a group inside itself.")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.tertiary))

                    if let problem = store.problem(for: "parent_id") {
                        Text(problem)
                            .font(Typography.caption.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.critical))
                    }
                }

                ContentSection("Split", showsRule: false, appearance: appearance) {
                    if group.hasChildren {
                        Text("This already has sub-groups. Splitting again would add more "
                             + "beside them, so it is offered only on a group that has none.")
                            .font(Typography.caption.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    } else if isSplitting {
                        Text("\(group.headcount) students, divided as evenly as they go.")
                            .font(Typography.caption.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                        Field(
                            label: "How many batches",
                            placeholder: "3",
                            value: $batches,
                            appearance: appearance
                        )
                        .frame(maxWidth: 180)
                        HStack(spacing: Spacing.regular.points) {
                            ActionButton(emphasis: .primary, appearance: appearance) {
                                if case .success(let count) = NumberEntry.count(batches) {
                                    isSplitting = false
                                    Task { await store.split(group, into: count) }
                                }
                            } label: {
                                Text("Split")
                            }
                            ActionButton(appearance: appearance) { isSplitting = false } label: {
                                Text("Cancel")
                            }
                        }
                    } else {
                        ActionButton(appearance: appearance) { isSplitting = true } label: {
                            Text("Split into batches…")
                        }
                    }
                }
            }
        }
        .task(id: group.id) {
            name = group.name
            size = String(group.size)
            programID = group.programID
            parentID = group.parentID
            memberIDs = group.memberIDs
            isSplitting = false
            batches = "3"
        }
    }

    private func commit() {
        var edited = group
        edited.name = name
        edited.programID = programID
        edited.memberIDs = memberIDs
        switch NumberEntry.count(size) {
        case .success(let value):
            store.complain(nil, about: "size")
            edited.size = value
        case .failure(let complaint):
            store.complain(complaint.message, about: "size")
            return
        }
        Task { await store.save(edited, movingTo: parentID) }
    }
}
