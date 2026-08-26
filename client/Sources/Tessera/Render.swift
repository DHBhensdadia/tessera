import AppKit
import DesignSystem
import EngineClient
import SwiftUI

/// `--render <screen> <file.png>` — draw a screen offscreen, against a real engine.
///
/// The `Snapshot` target has rendered the *design system* this way since 3.1b, and its
/// docstring says exactly why: `screencapture` needs a Screen Recording grant that a build
/// machine will never have, so a design could be built and never seen by whoever built it.
///
/// That reasoning applies just as well to the application's own screens, and for a phase it
/// was not applied to them — 3.4 and 3.4b were photographed with `screencapture`, which cost
/// the better part of two sittings to permission revocations, windows opening on other
/// Spaces, duplicate windows that photographed the wrong one, and content below the fold of
/// a window that could not be made taller than the display. None of those exist here:
/// `ImageRenderer` draws into a bitmap in process, at the view's full intrinsic height,
/// with no window server involved.
///
/// `Snapshot` could not do this because it depends on `DesignSystem` alone. These screens
/// need an engine, so the renderer lives where the engine client already is.
///
/// **What it cannot show.** The same limit `Snapshot` records: `glassEffect` renders as
/// nothing offscreen, because Liquid Glass needs the compositor. So the sidebar and toolbar
/// are not here — this draws the content pane, which is what a screen *is*. Chrome is
/// judged in a window, by a person.
@MainActor
enum Render {
    static func run() async {
        guard let (screen, output) = arguments() else {
            say("render: expected --render <screen> <file.png>")
            exit(2)
        }
        guard let project = ProjectChooser.projectsNamed().first else {
            say("render: --render needs --open <project>")
            exit(2)
        }

        let engine = EngineController(location: ProjectLocation(project, intent: .reopen))
        await engine.start()
        guard case .running(let running) = engine.state else {
            say("render: the engine did not start — \(engine.state)")
            exit(1)
        }
        defer { engine.stop() }
        let connection = EngineConnection(port: running.port, token: running.token)

        guard let term = try? await connection.run({
            try await $0.listTerms(.init()).ok.body.json
        }).items.first?.id else {
            say("render: the project has no term, so there is nothing term-scoped to draw")
            exit(1)
        }

        guard let view = await view(for: screen, connection: connection, term: term) else {
            say("render: no renderer for '\(screen.rawValue)' yet")
            exit(2)
        }

        guard let data = png(of: view) else {
            say("render: the view produced no bitmap")
            exit(1)
        }
        try? data.write(to: URL(filePath: output))
        say("render: wrote \(output)")
        exit(0)
    }

    /// Every screen that can be drawn without a window, and how to fill it first.
    ///
    /// Each case loads its own store and hands it over already filled: `ImageRenderer` has
    /// no run loop, so `.task` never fires and a screen that loads itself renders empty.
    private static func view(
        for screen: Destination,
        connection: EngineConnection,
        term: Int
    ) async -> AnyView? {
        let appearance = Appearance(scheme: .dark)
        switch screen {
        case .constraints:
            let store = ConstraintStore(connection: connection, term: term)
            await store.load()
            return AnyView(ConstraintsScreen(loaded: store, appearance: appearance).content)
        default:
            return nil
        }
    }

    private static func arguments() -> (Destination, String)? {
        let arguments = CommandLine.arguments
        guard let index = arguments.firstIndex(of: "--render"), index + 2 < arguments.count,
              let screen = Destination(rawValue: arguments[index + 1])
        else { return nil }
        return (screen, arguments[index + 2])
    }

    /// Width is fixed and height is not: the point of drawing offscreen is that a screen
    /// taller than the display is still one picture.
    private static func png(of view: some View) -> Data? {
        let renderer = ImageRenderer(
            content: view
                .frame(width: 1_040)
                .background(Appearance(scheme: .dark).swiftUI(SurfaceRole.base))
        )
        // Retina, because half the point is judging type and hairlines.
        renderer.scale = 2
        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff) else { return nil }
        return bitmap.representation(using: .png, properties: [:])
    }

    private static func say(_ line: String) {
        FileHandle.standardError.write(Data((line + "\n").utf8))
    }
}
