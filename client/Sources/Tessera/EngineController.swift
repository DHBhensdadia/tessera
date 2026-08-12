import Foundation
import Observation
import os

/// Launches the bundled engine and keeps the application's view of it current.
///
/// The engine is a frozen Python process shipped inside the app bundle. It binds a
/// loopback port the kernel chooses and writes one JSON line to stdout before serving
/// anything, so the port and token are discovered rather than agreed in advance.
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

    private(set) var state: State = .idle
    private var process: Process?

    // MARK: - Lifecycle

    func start() async {
        stop()
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
            state = .failed(error)
        } catch {
            state = .failed(.unexpected(String(describing: error)))
        }
    }

    func stop() {
        process?.terminate()
        process = nil
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
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        self.process = process

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
