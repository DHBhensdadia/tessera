import AppKit
import SwiftUI

/// One engine per project, made structural instead of hoped for.
///
/// The first version of this held the controller in the project window's own `@State`,
/// created in `init`. That looks right and is not: SwiftUI re-evaluates a view struct
/// whenever anything upstream changes, `init` runs every time, and a window that should
/// have had one engine ended up starting **six** — measured on the shipped bundle, one
/// project open. `@State` keeps the first value it is given, but it does not stop a view
/// whose identity changes from getting a fresh one, and each fresh one runs `.task`.
///
/// So ownership moves to a registry keyed by the project itself. A location maps to
/// exactly one controller, whoever asks and however often, and the identity of the engine
/// no longer depends on the lifecycle of a struct. The rule the engine set in 2.9 — one
/// engine serves one project for its whole life — is now enforced by the type that hands
/// them out rather than by a view remembering not to make another.
///
/// It is *not* an app-owned engine by the back door: the registry never starts anything
/// on its own, and `release` tears the engine down when its window closes. What it owns is
/// the mapping, which is precisely the part that must not be duplicated.
/// **Deliberately not `@Observable`.** The registry is a lookup table, not something any
/// view renders: views observe the *controller* they were handed, never the mapping. Making
/// it observable meant `controller(for:)` — which inserts on a miss — mutated observed
/// state *during* body evaluation, SwiftUI discarded and re-ran the pass, and the second
/// pass built a second controller. Two projects open produced **four** engines, exactly two
/// per project, every one a direct child of the app. Nothing in the code read as wrong; the
/// process tree was the only thing that said so.
@MainActor
final class EngineRegistry {
    private var controllers: [ProjectLocation: EngineController] = [:]

    /// The engine for this project, creating it the first time and only the first time.
    func controller(for location: ProjectLocation) -> EngineController {
        if let existing = controllers[location] { return existing }
        let created = EngineController(location: location)
        controllers[location] = created
        return created
    }

    /// Bring an already-open project forward. `true` if there was one.
    ///
    /// Checked before opening, because `WindowGroup(for:)` does **not** focus an existing
    /// window for a value it already has one for — measured twice: re-opening two open
    /// projects took the engine count from two to four. The plan's D1 assumed that
    /// guarantee; it does not hold.
    ///
    /// **The window is found by asking AppKit, not by a map this class maintains.**
    /// `.navigationDocument(url)` on the project window sets `NSWindow.representedURL`, so
    /// the association already exists in state the system keeps up to date. A registration
    /// of our own had to happen at some moment during launch, and the moment it actually
    /// happened was after the first re-open — windows created from launch arguments were
    /// never recorded, so the first re-open made a second pair and only later ones
    /// focused. Reading what AppKit already knows has no such moment to miss.
    func focusIfOpen(_ location: ProjectLocation) -> Bool {
        let match = NSApplication.shared.windows.first { window in
            window.isVisible
                && window.representedURL?.standardizedFileURL == location.url
        }
        guard let match else { return false }
        NSApplication.shared.activate(ignoringOtherApps: true)
        match.makeKeyAndOrderFront(nil)
        return true
    }

    /// The window for this project has gone. So does its engine.
    ///
    /// Explicit rather than relying on deinit: the engine is a subprocess, and a Python
    /// process that outlives the window it belonged to is not a leak the user can see or
    /// clean up. Closing eight windows must leave zero engines.
    func release(_ location: ProjectLocation) {
        controllers.removeValue(forKey: location)?.stop()
    }

    /// How many engines are alive. Exists for the test that closing windows closes them.
    var count: Int { controllers.count }
}

private struct EngineRegistryKey: EnvironmentKey {
    /// Never used: `TesseraApp` injects the real one into both scenes. A default is
    /// required by `EnvironmentKey`, and one that quietly hands out a *second* registry
    /// would reintroduce the bug this file exists to prevent — so it is the same instance
    /// every time rather than a fresh one.
    @MainActor static let shared = EngineRegistry()
    static var defaultValue: EngineRegistry { MainActor.assumeIsolated { shared } }
}

extension EnvironmentValues {
    var engineRegistry: EngineRegistry {
        get { self[EngineRegistryKey.self] }
        set { self[EngineRegistryKey.self] = newValue }
    }
}
