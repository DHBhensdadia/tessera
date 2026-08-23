import EngineClient
import Foundation

/// `--probe` — exercise the client against a real engine, including the failures.
///
/// It exists because a generated client compiles against a *document*, not against a
/// server, so "it builds" proves close to nothing. Three defects in this phase were
/// invisible to the compiler and to the suites: a plugin that generated nothing, a base URL
/// that doubled the path prefix, and a typed failure the generated code wrapped in a
/// `ClientError` so no call site could catch it.
///
/// Every call goes through `connection.run`, which is exactly what 3.4's screens will do.
@MainActor
enum Probe {
    static func run() async {
        let engine = EngineController(location: ProjectLocation(temporaryProject(), intent: .create))
        await engine.start()

        guard case .running(let running) = engine.state else {
            say("probe: the engine did not start — \(engine.state)")
            exit(1)
        }
        let connection = EngineConnection(port: running.port, token: running.token)

        do {
            let institution = try await succeeds(connection)
            try await refusesADuplicate(connection, institution: institution)
            try await complainsAboutAField(connection, institution: institution)
            try await reportsSomethingMissing(connection)
            await noticesTheEngineHasGone(engine, connection)
            engine.stop()
            exit(0)
        } catch {
            say("probe: unexpected — \(EngineFailure.unwrap(error).message)")
            engine.stop()
            exit(1)
        }
    }

    /// The happy path: a write, then a read that proves the write landed.
    private static func succeeds(_ connection: EngineConnection) async throws -> Int {
        let created = try await connection.run {
            try await $0.createInstitution(body: .json(.init(name: "Probe University"))).created.body.json
        }
        let page = try await connection.run {
            try await $0.listInstitutions().ok.body.json
        }
        say("ok        wrote and read back — total=\(page.total), first=\(page.items.first?.name ?? "none")")
        return created.id
    }

    /// A 409: the engine refusing on a rule, in the sentence it already wrote.
    private static func refusesADuplicate(_ connection: EngineConnection, institution: Int) async throws {
        _ = try await connection.run {
            try await $0.createBuilding(body: .json(.init(institution_id: institution, name: "Block A")))
        }
        do {
            _ = try await connection.run {
                try await $0.createBuilding(body: .json(.init(institution_id: institution, name: "Block A")))
            }
            say("MISSING   a duplicate building was accepted")
        } catch let failure as EngineFailure {
            say("refused   \(failure.problem?.status ?? 0) \(failure.problem?.title ?? "?") — \(failure.message)")
            say("          transient? \(failure.isTransient)  — a refusal is a decision, so no retry")
        }
    }

    /// A 422: a complaint about one field, which a form has to place beside that field.
    private static func complainsAboutAField(_ connection: EngineConnection, institution: Int) async throws {
        do {
            _ = try await connection.run {
                try await $0.createBuilding(body: .json(.init(institution_id: institution, name: "")))
            }
            say("MISSING   an empty building name was accepted")
        } catch let failure as EngineFailure {
            say("refused   \(failure.problem?.status ?? 0) — \(failure.message)")
            for field in failure.fields {
                let hint = field.hint.isEmpty ? "" : "  hint: \(field.hint)"
                say("          field '\(field.fieldName)' (\(field.pointer)): \(field.message)\(hint)")
            }
            if failure.fields.isEmpty {
                say("          NO FIELD DETAIL — a form could not place this beside an input")
            }
        }
    }

    private static func reportsSomethingMissing(_ connection: EngineConnection) async throws {
        do {
            _ = try await connection.run {
                try await $0.getBuilding(path: .init(building_id: 999_999))
            }
            say("MISSING   a nonexistent building was returned")
        } catch let failure as EngineFailure {
            say("refused   \(failure.problem?.status ?? 0) \(failure.problem?.title ?? "?")")
        }
    }

    /// The engine dying underneath a live request — the case D6 exists for.
    private static func noticesTheEngineHasGone(
        _ engine: EngineController, _ connection: EngineConnection
    ) async {
        engine.stop()
        try? await Task.sleep(for: .milliseconds(600))
        do {
            _ = try await connection.run { try await $0.listBuildings() }
            say("MISSING   a dead engine answered")
        } catch let failure as EngineFailure {
            say("gone      \(failure.message)")
            say("          transient? \(failure.isTransient)  — so the retries above were worth making")
        } catch {
            say("gone      untyped: \(error)")
        }
    }

    private static func temporaryProject() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appending(path: "probe-\(UUID().uuidString).tessera")
    }

    private static func say(_ line: String) {
        FileHandle.standardError.write(Data((line + "\n").utf8))
    }
}
