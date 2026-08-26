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

    /// Windows this registry is closing because they are duplicates.
    ///
    /// A window closed for that reason must not take the project's engine with it, and
    /// `release` cannot tell on its own: it asks whether any *other* window still shows the
    /// project, and during a collapse the survivor may not have its `representedURL` yet —
    /// `.navigationDocument` sets it when the window attaches, and attaching is exactly when
    /// the collapse runs. So `release` saw no sibling, stopped the engine, and both windows
    /// sat on "Opening…" for ever with no engine and no error.
    ///
    /// Recording the intent removes the guesswork. Identity rather than the window itself,
    /// so nothing here keeps a closed window alive.
    private var collapsing: Set<ObjectIdentifier> = []

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

    /// The window for this project has gone. So does its engine — unless another window
    /// is still showing the same project.
    ///
    /// Explicit rather than relying on deinit: the engine is a subprocess, and a Python
    /// process that outlives the window it belonged to is not a leak the user can see or
    /// clean up. Closing eight windows must leave zero engines.
    ///
    /// The guard is not hypothetical. Scene restoration replays **one window per persisted
    /// entry**, and it does not deduplicate by value — so a project opened twelve times over
    /// a month comes back as twelve windows onto one file. `collapseDuplicates` closes the
    /// extras, and without this check the first close would stop the engine the survivor is
    /// still using.
    ///
    /// The closing window is excluded explicitly because it is still in `windows` and still
    /// reports `isVisible` while `willCloseNotification` is being delivered — asking "is
    /// anyone else showing this?" while counting yourself always answers yes.
    func release(_ location: ProjectLocation, closing window: NSWindow? = nil) {
        // A duplicate being collapsed is not the project closing.
        if let window, collapsing.remove(ObjectIdentifier(window)) != nil { return }

        let elsewhere = NSApplication.shared.windows.contains {
            $0 !== window && $0.isVisible && $0.representedURL?.standardizedFileURL == location.url
        }
        guard !elsewhere else { return }
        controllers.removeValue(forKey: location)?.stop()
    }

    /// Close every window but one for a project that has several.
    ///
    /// Restoration is the only thing that produces them: `focusIfOpen` already prevents a
    /// second window at runtime, and nothing in the interface offers to open one. But
    /// `WindowGroup(for:)` persists a window per *opening* rather than per value, so every
    /// launch that named the same project on the command line — or every reopen from Recent
    /// Projects — left another entry to replay. Measured on the shipped bundle: **twelve
    /// windows onto one project**, plus three more for projects last opened days earlier.
    ///
    /// Found because `screencapture` began refusing a window id that the window server was
    /// perfectly happy to hand out, which is a strange enough symptom to chase.
    ///
    /// The survivor is the lowest window number — the oldest — so every duplicate running
    /// this reaches the same answer and the order they run in does not matter.
    func collapseDuplicates(of location: ProjectLocation) {
        let showing = NSApplication.shared.windows
            .filter { $0.representedURL?.standardizedFileURL == location.url }
            .sorted { $0.windowNumber < $1.windowNumber }
        for extra in showing.dropFirst() {
            collapsing.insert(ObjectIdentifier(extra))
            extra.close()
        }
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
