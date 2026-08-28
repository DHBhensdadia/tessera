import Foundation
import Testing

@testable import Tessera

/// That a screen's store outlives the body evaluation that drew it.
///
/// The defect this exists for shipped and was found by looking at the screen: Buildings
/// said "No buildings yet" while the sidebar beside it counted two. The store was built by
/// the shell and handed to the screen as a `let`, so the sequence was —
///
/// 1. `body` runs, a store is built, `.task` calls `load()`.
/// 2. `load()` sets `items`, which is `@Observable`, which invalidates `body`.
/// 3. `body` runs again and builds a **second, empty** store.
/// 4. `.task(id:)` does not re-fire, because the id it was keyed on had not changed.
///
/// The list is then empty for as long as the window is open. Nothing catches it: the code
/// compiles, every suite passes, and the store's own `load()` is correct — it ran, it got
/// its rows, and they were thrown away by the next render. The same shape as the engine
/// registry in 3.2, where an `@Observable` mutated during `body` produced a second engine.
///
/// So the rule is structural and checked here: a view that owns a store declares it
/// `@State`, and the shell never constructs one. `.id(...)` at the call site is what gives
/// each destination a fresh store — a different identity discards the old `@State` with it.
struct StoreOwnershipTests {
    private static var sources: URL {
        var url = URL(fileURLWithPath: #filePath)
        while url.pathComponents.count > 1 {
            url.deleteLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appending(path: "Package.swift").path) {
                return url.appending(path: "Sources/Tessera")
            }
        }
        Issue.record("could not find Package.swift above \(#filePath)")
        return url
    }

    private func read(_ path: String) throws -> String {
        try String(contentsOf: Self.sources.appending(path: path), encoding: .utf8)
    }

    /// Every screen holds its own store, in the one property wrapper that survives a
    /// redraw.
    @Test(arguments: [
        "Data/Rooms/RoomsScreen.swift",
        "Data/SimpleEntity.swift",
        "Data/People/InstructorsScreen.swift",
        "Data/Courses/CoursesScreen.swift",
        "Data/Groups/GroupsScreen.swift",
        "Data/Teaching/OfferingsScreen.swift",
    ])
    func aScreenOwnsItsStoreInState(file: String) throws {
        // The bool is extracted rather than inlined so a failure prints the sentence and
        // not the entire file the expectation happened to read.
        let owned = try read(file).contains("@State private var store")
        #expect(owned,
                "\(file) does not own its store — a redraw will replace it and drop what it loaded")
    }

    /// And the shell builds none of them.
    ///
    /// A helper on the shell that returns `SomeScreen(store: SomeStore(…))` reads as
    /// factoring out duplication and is the defect itself: the shell's `body` re-runs
    /// whenever anything it observes changes, and every re-run makes another store.
    @Test func theShellConstructsNoStores() throws {
        let source = try read("Project/ProjectWindow.swift")
        let offenders = source
            .split(separator: "\n")
            .filter { $0.contains("Store(") && !$0.trimmingCharacters(in: .whitespaces).hasPrefix("///") }
        #expect(offenders.isEmpty,
                "ProjectWindow builds a store during body evaluation: \(offenders.joined(separator: " / "))")
    }

    /// The mechanism that makes `@State` correct here rather than sticky.
    ///
    /// Without a per-destination identity the first store would be kept for all four
    /// screens, and Features would list buildings. That was the reason the store was
    /// passed in to begin with, so the replacement has to carry it.
    @Test func eachSimpleScreenGetsItsOwnIdentity() throws {
        let keyed = try read("Project/ProjectWindow.swift").contains(".id(title)")
        #expect(keyed,
                "the four name-only screens share one view identity, so they will share one store")
    }
}
