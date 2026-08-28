import EngineClient
import Testing

@testable import Tessera

/// That the outline draws the tree it was given.
///
/// P7: *"the tree is the UI because it is the data model."* The hierarchy arrives already
/// resolved from `groupTree`, so nothing here rebuilds parent/child rules — what is worth
/// testing is the flattening and the collapse, which are this screen's own and are the two
/// places an outline usually goes wrong.
@MainActor
struct GroupOutlineTests {
    private func node(
        _ id: Int,
        _ name: String,
        depth: Int,
        hasChildren: Bool = false
    ) -> GroupStore.Group {
        GroupStore.Group(
            id: id,
            name: name,
            size: 0,
            headcount: 0,
            programID: nil,
            parentID: nil,
            isCohort: false,
            memberIDs: [],
            depth: depth,
            hasChildren: hasChildren
        )
    }

    /// programme root → intake → three batches, as P7 draws it.
    private var tree: [GroupStore.Group] {
        [
            node(1, "2024 Intake", depth: 0, hasChildren: true),
            node(2, "Batch A", depth: 1, hasChildren: true),
            node(3, "Batch A1", depth: 2),
            node(4, "Batch A2", depth: 2),
            node(5, "Batch B", depth: 1),
            node(6, "2025 Intake", depth: 0),
        ]
    }

    @Test func everythingOpenShowsEverything() {
        let open = Set([1, 2])
        #expect(GroupStore.visible(in: tree, expanded: open).map(\.id) == [1, 2, 3, 4, 5, 6])
    }

    /// Collapsing a node hides its **whole** subtree, not just its children. Hiding one
    /// level would leave grandchildren indented under a parent that is no longer drawn.
    @Test func collapsingHidesTheWholeSubtree() {
        let shown = GroupStore.visible(in: tree, expanded: [2])
        #expect(shown.map(\.id) == [1, 6], "collapsing the intake must take its batches with it")
    }

    @Test func collapsingOneBranchLeavesItsSiblingsAlone() {
        let shown = GroupStore.visible(in: tree, expanded: [1])
        #expect(shown.map(\.id) == [1, 2, 5, 6])
    }

    /// A leaf has no disclosure control, because one that does nothing is worse than none.
    @Test func onlyBranchesGetATwisty() {
        let store = GroupStore(connection: .init(port: 1, token: ""))
        #expect(store.nesting(of: node(3, "Batch A1", depth: 2)).isExpanded == nil)
        #expect(store.nesting(of: node(1, "Intake", depth: 0, hasChildren: true)).isExpanded != nil)
        #expect(store.nesting(of: node(3, "Batch A1", depth: 2)).depth == 2)
    }

    /// Flattening puts a node immediately before its descendants, which is what makes the
    /// collapse walk above correct — it relies on reading order, not on ids.
    @Test func flatteningIsDepthFirstInReadingOrder() {
        let leaf = { (id: Int, name: String) in
            Components.Schemas.StudentGroupTree(id: id, kind: .structural, name: name, size: 10)
        }
        var intake = Components.Schemas.StudentGroupTree(
            id: 1, kind: .structural, name: "2024 Intake", size: 0
        )
        intake.children = [leaf(2, "Batch A"), leaf(3, "Batch B")]

        var flat: [GroupStore.Group] = []
        GroupStore.flatten(intake, depth: 0, parent: nil, into: &flat)

        #expect(flat.map(\.name) == ["2024 Intake", "Batch A", "Batch B"])
        #expect(flat.map(\.depth) == [0, 1, 1])
        #expect(flat.map(\.parentID) == [nil, 1, 1])
        #expect(flat[0].hasChildren)
        #expect(!flat[1].hasChildren)
    }
}
