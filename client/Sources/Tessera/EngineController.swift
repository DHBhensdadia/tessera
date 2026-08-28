import Foundation
import Observation
import os

/// Launches the bundled engine for **one project** and keeps the window's view of it
/// current.
///
/// The engine is a frozen Python process shipped inside the app bundle. It binds a
/// loopback port the kernel chooses and writes one JSON line to stdout before serving
/// anything, so the port and token are discovered rather than agreed in advance.
///
/// **One engine serves one project for its whole life**, which is a rule the engine set
/// in 2.9 rather than a convenience here: an endpoint that swapped the project underneath
/// a running server would make the engine's identity mutable, invalidate every open
/// session, and give the token a second meaning. So a controller is owned by a project
/// window, created when it opens and stopped when it closes — not by the application.
///
/// The cost is stated rather than engineered around: *n* open projects means *n* Python
/// processes at roughly 40–60 MB each. Three or four is realistic; the alternative is a
/// multi-project engine, which is precisely what 2.9 argued against.
///
/// Every failure path here ends in a message naming what went wrong. An engine that
/// cannot start must never leave the interface on a spinner.
@Observable
@MainActor
final class EngineController {
    enum State {
        case idle
        case starting(String)
        case running(Engine)
        case failed(EngineError)
        /// The project could not be opened, and it is the user's file rather than a bug.
        /// Kept apart from `failed` because the sentence and the offer are different: one
        /// of these is something to report, the other is something to fix.
        case unopenable(ProjectProblem)

        var isPending: Bool {
            if case .starting = self { return true }
            return false
        }
    }

    struct Engine {
        let port: Int
        let token: String
        let pid: Int
        let project: String
        var health: Health?
    }

    struct Health: Decodable {
        let status: String
        let version: String
        let pid: Int
        let project: String
        let database: String
    }

    private struct Handshake: Decodable {
        let port: Int
        let token: String
        let pid: Int
        let project: String
    }

    let location: ProjectLocation
    private(set) var state: State = .idle
    private var hasLaunched = false

    /// Held outside the actor so that a controller dropped without `stop()` — a path
    /// nobody intends — still takes its subprocess with it. A Python process outliving
    /// the window it belonged to is not a leak the user can see or clean up.
    private let launched = LaunchedProcess()

    init(location: ProjectLocation) {
        self.location = location
    }

    // MARK: - Lifecycle

    /// Launch the engine, at most once.
    ///
    /// The guard is the whole point. `start()` is called from `.task`, and SwiftUI will
    /// run that more than once for what the user thinks of as one window — a second
    /// project opening, a re-evaluation, a restored scene settling. Without it, two calls
    /// both found `state == .idle`, both got past `stop()` with nothing to stop, and both
    /// launched: **two projects produced four engines**, one of each pair orphaned the
    /// moment the second overwrote the reference to the first.
    ///
    /// Set before the first `await`, so there is no window between the check and the
    /// claim — on the main actor that makes it atomic without a lock.
    /// The launch runs in a task this controller owns, not the caller's.
    ///
    /// `start()` is awaited from a view's `.task`, which dies with the view — and a window
    /// can go away for reasons that have nothing to do with the project: a duplicate being
    /// collapsed is one, and it takes the *shared* controller's launch with it. The window
    /// that survives then shows "the engine started but never became ready — cancelled" for
    /// an engine it still needs and cannot restart, because `hasLaunched` is already true.
    ///
    /// An unstructured task is not cancelled when the caller is, so the launch finishes and
    /// `state` reaches `.running` whoever is still watching. Which is right on its own
    /// terms: the engine belongs to the registry, and the registry outlives every window.
    private var launch: Task<Void, Never>?

    func start() async {
        guard !hasLaunched else { return }
        hasLaunched = true
        let work = Task { await self.performLaunch() }
        launch = work
        await work.value
    }

    private func performLaunch() async {
        state = .starting("Locating engine…")

        guard let executable = Self.locateEngine() else {
            state = .failed(.notBundled)
            return
        }

        state = .starting("Starting engine…")
        do {
            let handshake = try await launch(executable)
            state = .starting("Waiting for engine…")
            let health = try await waitForHealth(port: handshake.port, token: handshake.token)
            state = .running(
                Engine(
                    port: handshake.port,
                    token: handshake.token,
                    pid: handshake.pid,
                    project: handshake.project,
                    health: health
                )
            )
        } catch let error as EngineError {
            // An exit status the engine defines for a file the user moved or replaced is
            // not an engine failure, and must not be reported as one.
            if case .exited(let status, _) = error,
               let problem = ProjectProblem(exitStatus: status, location: location) {
                state = .unopenable(problem)
            } else {
                state = .failed(error)
            }
        } catch {
            state = .failed(.unexpected(String(describing: error)))
        }
    }

    /// The engine is fine and the project it opened could not be set up.
    ///
    /// Its own state rather than a variant of `failed`, because the engine did start: the
    /// window can still be used, and the thing that went wrong is one step of creation.
    func reportSetupFailure(_ detail: String) {
        state = .failed(.unexpected("The project was created but could not be set up. \(detail)"))
    }

    func stop() {
        hasLaunched = false
        launched.terminate()
    }

    /// What the engine is told, given what it is being asked to open.
    ///
    /// A static function rather than three lines inside `launch` so it can be tested: the
    /// intent crossing this boundary is the only thing standing between "this project has
    /// moved" and an empty project wearing its name, and it is exactly the kind of thing
    /// that is fixed once and quietly reverted later.
    ///
    /// The path is passed unescaped. `URL.path` percent-encodes, and a Mac path with a
    /// space in it — which is most of them — would arrive at the engine as a literal
    /// `%20` and open a project nobody has.
    nonisolated static func arguments(for location: ProjectLocation) -> [String] {
        var arguments = ["--project", location.url.path(percentEncoded: false)]
        if location.intent == .reopen {
            arguments.append("--must-exist")
        }
        return arguments
    }

    private static func locateEngine() -> URL? {
        let bundled = Bundle.main.resourceURL?.appending(path: "engine/tessera-engine")
        if let bundled, FileManager.default.isExecutableFile(atPath: bundled.path) {
            return bundled
        }
        // Running from Xcode or `swift run`, where no bundle exists yet.
        if let override = ProcessInfo.processInfo.environment["TESSERA_ENGINE"],
           FileManager.default.isExecutableFile(atPath: override) {
            return URL(filePath: override)
        }
        return nil
    }

    // MARK: - Handshake

    /// Accumulates stdout until a usable handshake line arrives.
    ///
    /// `readabilityHandler` fires on an arbitrary queue and `terminationHandler` on
    /// another, so all shared state sits behind one lock. `resumed` is the important
    /// part: three paths race to finish this operation — the handshake, an early exit,
    /// and the timeout — and a continuation resumed twice crashes. An engine that
    /// prints and *then* dies triggers two of them.
    private struct Pending {
        var buffer = Data()
        var resumed = false
    }

    private func launch(_ executable: URL) async throws -> Handshake {
        let process = Process()
        process.executableURL = executable
        process.arguments = Self.arguments(for: location)
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        launched.hold(process)

        let outHandle = stdout.fileHandleForReading
        let errHandle = stderr.fileHandleForReading

        try process.run()

        return try await withCheckedThrowingContinuation {
            (continuation: CheckedContinuation<Handshake, Error>) in
            let pending = OSAllocatedUnfairLock(initialState: Pending())

            @Sendable func finish(_ result: Result<Handshake, Error>) {
                let won = pending.withLock { state -> Bool in
                    guard !state.resumed else { return false }
                    state.resumed = true
                    return true
                }
                guard won else { return }
                continuation.resume(with: result)
            }

            outHandle.readabilityHandler = { handle in
                let chunk = handle.availableData
                guard !chunk.isEmpty else { return }

                let lines: [Data] = pending.withLock { state in
                    state.buffer.append(chunk)
                    var complete: [Data] = []
                    while let newline = state.buffer.firstIndex(of: UInt8(ascii: "\n")) {
                        complete.append(Data(state.buffer[..<newline]))
                        state.buffer.removeSubrange(...newline)
                    }
                    return complete
                }

                // Scan lines rather than trusting the first. The engine writes its logs
                // to stderr precisely so stdout stays clean, but a stray print from a
                // dependency should degrade into "keep looking", not a hard failure.
                for line in lines {
                    if let handshake = try? JSONDecoder().decode(Handshake.self, from: line) {
                        handle.readabilityHandler = nil
                        finish(.success(handshake))
                        return
                    }
                }
            }

            process.terminationHandler = { proc in
                let log = String(decoding: errHandle.readDataToEndOfFile(), as: UTF8.self)
                finish(.failure(EngineError.exited(status: proc.terminationStatus, log: log)))
            }

            Task {
                try? await Task.sleep(for: .seconds(20))
                finish(.failure(EngineError.noHandshake))
            }
        }
    }

    // MARK: - Health

    /// Polls until the engine answers, bounded by **total elapsed time**.
    ///
    /// The spike version multiplied an attempt count by a per-request timeout, so a
    /// hung engine could keep the interface waiting for ninety seconds while claiming
    /// to be starting. A deadline is what the user actually cares about.
    private func waitForHealth(
        port: Int,
        token: String,
        deadline: Duration = .seconds(15)
    ) async throws -> Health {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/health")!)
        request.setValue(token, forHTTPHeaderField: "x-tessera-token")
        request.timeoutInterval = 2

        let started = ContinuousClock.now
        var lastError: String = "no response"

        while ContinuousClock.now - started < deadline {
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    return try JSONDecoder().decode(Health.self, from: data)
                }
                lastError = "engine replied \((response as? HTTPURLResponse)?.statusCode ?? 0)"
            } catch {
                lastError = error.localizedDescription
            }
            try? await Task.sleep(for: .milliseconds(150))
        }
        throw EngineError.neverHealthy(lastError)
    }
}

/// A subprocess that terminates itself if it is ever dropped.
///
/// Not an over-abstraction: `deinit` on a `@MainActor` class cannot touch isolated state,
/// and the one thing that must survive every path out of this file is that the engine dies
/// with the thing that started it.
private final class LaunchedProcess: @unchecked Sendable {
    private let lock = OSAllocatedUnfairLock(initialState: Process?.none)

    func hold(_ process: Process) {
        lock.withLock { $0 = process }
    }

    func terminate() {
        lock.withLock { held -> Process? in
            defer { held = nil }
            return held
        }?.terminate()
    }

    deinit { terminate() }
}

enum EngineError: Error, CustomStringConvertible {
    case notBundled
    case exited(status: Int32, log: String)
    case noHandshake
    case neverHealthy(String)
    case unexpected(String)

    var description: String {
        switch self {
        case .notBundled:
            "The engine is missing from the application bundle."
        case .exited(let status, _):
            "The engine stopped unexpectedly (status \(status))."
        case .noHandshake:
            "The engine did not report a port within 20 seconds."
        case .neverHealthy(let reason):
            "The engine started but never became ready — \(reason)."
        case .unexpected(let detail):
            detail
        }
    }

    /// The engine's own output, shown so a failure can be diagnosed rather than only
    /// reported.
    var log: String? {
        if case .exited(_, let log) = self, !log.isEmpty { return log }
        return nil
    }
}
