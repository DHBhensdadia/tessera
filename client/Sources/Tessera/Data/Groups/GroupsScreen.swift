import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Student groups, as the tree they actually are.
///
/// P7 Act 5: *"The tree is the UI because it is the data model."* Groups are the one entity
/// in the application that is not a flat list — a programme has intakes, an intake splits
/// into lab batches — and 2.3 put the parent/child rules in the domain, including the
/// refusal to re-parent a group onto its own descendant.
///
/// The hierarchy is fetched already resolved (`groupTree`) rather than rebuilt here from
/// `parent_id`s. That is the engine's reasoning and it is right: rebuilding it in the client
/// would be a second implementation of the parent/child rules and a second place for them to
/// be wrong.
///
/// **Cohorts are roots with no children.** An elective drawing from three intakes is nobody's
/// child, so it cannot be nested — and hiding it would hide exactly the groups most likely to
/// cause conflicts. `kind` tells the two apart.
struct GroupsScreen: View {
    let appearance: Appearance

    @State private var store: GroupStore

    init(connection: EngineConnection, appearance: Appearance) {
        self.appearance = appearance
        _store = State(initialValue: GroupStore(connection: connection))
    }

    var body: some View {
        EntityWorkspace(
            title: "Student Groups",
            items: store.visible,
            label: \.name,
            value: { "\($0.headcount) students" },
            detail: { group in
                GroupDetail(group: group, store: store, appearance: appearance)
            },
            nesting: { store.nesting(of: $0) },
            toggle: { store.toggle($0) },
            adding: .blank { Task { await store.add() } },
            delete: { group in Task { await store.delete(group) } },
            deleteWarning: "A group with sub-groups will be refused, and Tessera will say how many.",
            selection: $store.selection,
            notice: store.notice,
            dismissNotice: { store.notice = nil },
            appearance: appearance
        )
        .task { await store.load() }
    }
}

@Observable
@MainActor
final class GroupStore {
    private let connection: EngineConnection

    /// The whole tree, flattened in reading order. Every node, whether or not it is shown.
    private(set) var all: [Group] = []
    /// Nodes whose children are drawn. Everything starts open: a tree that opens collapsed
    /// hides the data it exists to show, and these are tens of rows, not thousands.
    private var expanded: Set<Int> = []

    var selection: Group.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()
    var localProblems: [String: String] = [:]

    static let editableFields: Set<String> = ["name", "size", "parent_id", "program_id", "member_ids"]

    private(set) var programs: [Chooser.Option] = []

    struct Group: Identifiable, Sendable, Hashable {
        let id: Int
        var name: String
        /// What this group was told its own strength is.
        var size: Int
        /// What it actually amounts to — its own size, or the sum below it. The engine
        /// computes it; a field letting somebody type it would be a second answer.
        let headcount: Int
        var programID: Int?
        let parentID: Int?
        let isCohort: Bool
        var memberIDs: Set<Int>
        let depth: Int
        let hasChildren: Bool
    }

    init(connection: EngineConnection) {
        self.connection = connection
    }

    // MARK: - The outline

    /// The rows to draw: every node whose ancestors are all open.
    var visible: [Group] { Self.visible(in: all, expanded: expanded) }

    /// Pure, so the walk can be tested without an engine.
    ///
    /// The whole subtree of a collapsed node disappears, however deep — hiding only the
    /// immediate children would leave grandchildren stranded at their own indent under a
    /// parent that is no longer there.
    static func visible(in all: [Group], expanded: Set<Int>) -> [Group] {
        var shown: [Group] = []
        var hiddenBelow: Int?
        for group in all {
            if let depth = hiddenBelow {
                // Still inside the collapsed subtree while deeper than the node that closed.
                if group.depth > depth { continue }
                hiddenBelow = nil
            }
            shown.append(group)
            if group.hasChildren, !expanded.contains(group.id) { hiddenBelow = group.depth }
        }
        return shown
    }

    func nesting(of group: Group) -> Row.Nesting {
        Row.Nesting(
            depth: group.depth,
            isExpanded: group.hasChildren ? expanded.contains(group.id) : nil
        )
    }

    func toggle(_ group: Group) {
        guard group.hasChildren else { return }
        if expanded.contains(group.id) {
            expanded.remove(group.id)
        } else {
            expanded.insert(group.id)
        }
    }

    /// Every group, as options for choosing a parent.
    ///
    /// A group cannot be its own parent, and the engine refuses its own descendants — that
    /// refusal is left to the engine rather than reimplemented here, because "descendant"
    /// is a fact about the tree the engine already resolves and this would be a second
    /// implementation of it (#5). Self is removed because it needs no round trip to know.
    func parentOptions(for group: Group) -> [Chooser.Option] {
        all.filter { $0.id != group.id && !$0.isCohort }
            .map { .init(id: $0.id, name: String(repeating: "  ", count: $0.depth) + $0.name) }
    }

    /// Structural groups a cohort can draw students from.
    var memberOptions: [Chooser.Option] {
        all.filter { !$0.isCohort }.map { .init(id: $0.id, name: $0.name) }
    }

    // MARK: - Requests

    func load() async {
        do {
            let roots = try await connection.run { try await $0.groupTree(query: .init()).ok.body.json }
            var flat: [Group] = []
            for root in roots { Self.flatten(root, depth: 0, parent: nil, into: &flat) }
            // Anything not explicitly collapsed is open, including nodes that appeared
            // since the last load. Tracking the collapsed set instead would make a new
            // child arrive hidden under a parent somebody had never touched.
            expanded.formUnion(flat.filter(\.hasChildren).map(\.id))
            all = flat
            if selection == nil { selection = all.first?.id }

            programs = try await connection.run { try await $0.listPrograms().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    /// The tree, in the order it reads down the screen.
    static func flatten(
        _ node: Components.Schemas.StudentGroupTree,
        depth: Int,
        parent: Int?,
        into flat: inout [Group]
    ) {
        let children = node.children ?? []
        flat.append(
            Group(
                id: node.id,
                name: node.name,
                size: node.size,
                headcount: node.headcount ?? node.size,
                programID: node.program_id,
                parentID: parent,
                isCohort: node.kind == .cohort,
                memberIDs: [],
                depth: depth,
                hasChildren: !children.isEmpty
            )
        )
        for child in children { flatten(child, depth: depth + 1, parent: node.id, into: &flat) }
    }

    func add() async {
        forgetLastRefusal()
        let name = uniqueName()
        do {
            _ = try await connection.run {
                var body = Components.Schemas.StudentGroupCreate(name: name)
                body.size = 30
                return try await $0.createGroup(body: .json(body)).created.body.json
            }
            await load()
            selection = all.first { $0.name == name }?.id ?? selection
        } catch {
            report(error)
        }
    }

    /// Save, optionally moving the group somewhere else in the tree.
    ///
    /// The parent travels as an argument rather than as a mutable field on `Group`, because
    /// everywhere *else* the parent is a fact read from the resolved tree and not something
    /// a view should be able to set by assignment. A move is a deliberate call.
    func save(_ group: Group, movingTo parent: Int?) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var changes = Components.Schemas.StudentGroupUpdate()
                changes.name = group.name
                changes.size = group.size
                changes.program_id = group.programID
                changes.parent_id = parent
                if group.isCohort { changes.member_ids = Array(group.memberIDs).sorted() }
                return try await $0.updateGroup(
                    path: .init(group_id: group.id), body: .json(changes)
                ).ok
            }
            // Re-read the whole tree: a re-parent moves a subtree and changes the headcount
            // of two branches, and patching that locally is the parent/child rules written
            // a second time.
            await load()
        } catch {
            // 2.3 refuses a cycle and a re-parent onto a descendant, with a sentence.
            report(error)
        }
    }

    func delete(_ group: Group) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run { try await $0.deleteGroup(path: .init(group_id: group.id)) }
            selection = nil
            await load()
        } catch {
            // #48: refused while sub-groups hang off it, and it says how many.
            report(error)
        }
    }

    /// P7: *"Adding a sub-batch is right-click → Split into Lab Batches, which asks how many
    /// and divides the strength."*
    ///
    /// The parent keeps its name and loses its own size, because after a split the students
    /// *are* the batches — the parent's headcount then derives from them, which is what
    /// makes editing one batch move the intake's total. The remainder is spread over the
    /// first few rather than dropped, so the batches still add up to what was typed.
    func split(_ group: Group, into count: Int) async {
        forgetLastRefusal()
        guard count >= 2 else {
            notice = "A split needs at least two batches."
            return
        }
        let total = group.headcount
        let base = total / count
        let remainder = total % count
        do {
            for index in 0..<count {
                let size = base + (index < remainder ? 1 : 0)
                _ = try await connection.run {
                    var body = Components.Schemas.StudentGroupCreate(name: "Batch \(index + 1)")
                    body.size = size
                    body.parent_id = group.id
                    body.program_id = group.programID
                    return try await $0.createGroup(body: .json(body)).created
                }
            }
            var emptied = group
            emptied.size = 0
            await save(emptied, movingTo: group.parentID)
        } catch {
            report(error)
        }
    }

    func message(for field: String) -> String? { fieldErrors.message(for: field) }
    func complain(_ message: String?, about field: String) { localProblems[field] = message }
    func problem(for field: String) -> String? { localProblems[field] ?? message(for: field) }

    private func forgetLastRefusal() {
        notice = nil
        fieldErrors = FieldErrors()
    }

    private func report(_ error: any Error) {
        let failure = EngineFailure.unwrap(error)
        fieldErrors = FieldErrors.from(failure, fields: Self.editableFields)
        notice = fieldErrors.unrouted.isEmpty ? nil : fieldErrors.unrouted.joined(separator: "\n")
    }

    private func uniqueName() -> String {
        var candidate = "New Group"
        var suffix = 2
        while all.contains(where: { $0.name == candidate }) {
            candidate = "New Group \(suffix)"
            suffix += 1
        }
        return candidate
    }
}
