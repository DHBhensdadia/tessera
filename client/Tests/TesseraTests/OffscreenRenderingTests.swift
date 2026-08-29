import Foundation
import Testing

@testable import Tessera

/// That a list drawn into a bitmap is a list and not an empty column.
///
/// `ImageRenderer` renders a `ScrollView` as **nothing**. That is measured, and it has now
/// cost this project twice: `ConstraintsScreen` works around it by exposing its blocks
/// outside the scroll container, and `EntityWorkspace` could not, because scrolling there is
/// not incidental — a list of two hundred rooms genuinely needs it in a window.
///
/// So `ScrollsInAWindow` scrolls in a window and stacks in a bitmap, and these guard the two
/// halves of that. A plain `ScrollView` reintroduced into `EntityWorkspace` would compile,
/// pass every other test, and silently produce screenshots of empty lists — which is how
/// this kind of thing gets shipped.
struct OffscreenRenderingTests {
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

    /// The workspace every entity screen is built from uses the container that adapts.
    @Test func theWorkspaceScrollsOnlyInAWindow() throws {
        let source = try read("Data/EntityWorkspace.swift")

        #expect(!source.contains("ScrollView {"),
                "EntityWorkspace uses a bare ScrollView; offscreen it will render as nothing")
        #expect(source.contains("ScrollsInAWindow {"))
    }

    /// And the renderer actually turns the flag on.
    ///
    /// Without this the container is present, correct and never triggered — a guard nobody
    /// has watched fail, which this project has recorded as its own class of mistake.
    @Test func theRendererAsksForTheStackedForm() throws {
        let source = try read("Render.swift")

        #expect(source.contains("isRenderingOffscreen, true"),
                "--render does not set the environment, so lists will render as empty columns")
    }

    /// Rooms and Courses can be drawn from an already-loaded store.
    ///
    /// `ImageRenderer` has no run loop, so `.task` never fires: a screen that loads itself
    /// renders its empty state. The exit test for phase 4.0 part 2 is these two screens
    /// showing an imported instance, and it is reachable only through these initialisers.
    @Test(arguments: [
        "Data/Rooms/RoomsScreen.swift",
        "Data/Courses/CoursesScreen.swift",
        "Data/Rules/ConstraintsScreen.swift",
    ])
    func aRenderableScreenTakesALoadedStore(file: String) throws {
        #expect(try read(file).contains("init(loaded store:"),
                "\(file) cannot be drawn offscreen — it would render before its store loads")
    }
}
