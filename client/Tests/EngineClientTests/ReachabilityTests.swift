import Foundation
import Testing

@testable import EngineClient

/// That every operation in the contract is callable from Swift.
///
/// **What this actually covers, having been broken on purpose twice.**
///
/// It cannot fail by adding an operation to the document: the plugin regenerates from that
/// same document on the next build, so input and output are always consistent. The first
/// attempt to break it did exactly that and the test passed — a guard is only as good as
/// the way you try to defeat it.
///
/// It catches a generator **config** that drops operations — a `filter:` added to trim build
/// time is the realistic case — *for the operations nothing calls yet*, which today is
/// roughly a hundred of the hundred and nine. For the handful that are called, dropping them
/// is a compile error, which is stronger and arrives sooner.
///
/// A **stale** document is somebody else's job, and the chain is complete without this test
/// pretending to do it: the Python contract guard holds the app against
/// `docs/openapi.json`, `scripts/check.sh` holds that byte-identical against the copy beside
/// the generated code, and the plugin generates from that copy on every build.
struct ReachabilityTests {
    /// The document the generator actually reads, next to the generated code.
    static var document: [String: Any] {
        var url = URL(fileURLWithPath: #filePath)
        while url.pathComponents.count > 1 {
            url.deleteLastPathComponent()
            let candidate = url.appending(path: "Sources/EngineClient/openapi.json")
            if FileManager.default.fileExists(atPath: candidate.path) {
                let data = try! Data(contentsOf: candidate)
                return try! JSONSerialization.jsonObject(with: data) as! [String: Any]
            }
        }
        Issue.record("could not find Sources/EngineClient/openapi.json above \(#filePath)")
        return [:]
    }

    static var operationIDs: [String] {
        let paths = document["paths"] as? [String: Any] ?? [:]
        return paths.values.flatMap { path -> [String] in
            (path as? [String: Any] ?? [:]).values.compactMap {
                ($0 as? [String: Any])?["operationId"] as? String
            }
        }
    }

    /// Every operation id in the document exists as a method on the generated client.
    ///
    /// Checked by name against the generated source rather than by calling 109 methods:
    /// calling them would need a server, and this is a question about the *surface*.
    @Test func everyOperationInTheContractExistsOnTheClient() throws {
        let ids = Self.operationIDs
        #expect(ids.count > 100, "found only \(ids.count) operations — the document is not being read")

        let generated = try Self.generatedClientSource()
        let missing = ids.filter { !generated.contains("public func \($0)(") }
        #expect(
            missing.isEmpty,
            """
            \(missing.count) operations are in the contract and not on the client:
              \(missing.prefix(10).joined(separator: ", "))
            The generator is producing a subset — check the config for a filter, and that
            the document beside the generated code is the current one.
            """
        )
    }

    /// The generated `Client.swift`, wherever the plugin put it this build.
    static func generatedClientSource() throws -> String {
        var url = URL(fileURLWithPath: #filePath)
        while url.pathComponents.count > 1 {
            url.deleteLastPathComponent()
            let build = url.appending(path: ".build/plugins/outputs")
            guard FileManager.default.fileExists(atPath: build.path) else { continue }
            let walker = FileManager.default.enumerator(at: build, includingPropertiesForKeys: nil)
            for case let file as URL in walker!
            where file.lastPathComponent == "Client.swift" && file.path.contains("EngineClient") {
                return try String(contentsOf: file, encoding: .utf8)
            }
        }
        throw ReachabilityProblem.noGeneratedClient
    }

    enum ReachabilityProblem: Error { case noGeneratedClient }
}

/// That retry repeats what is safe and nothing else.
struct RetryPolicyTests {
    /// Never POST. A create that timed out after the engine wrote the row is
    /// indistinguishable from one that never arrived, and retrying makes two rooms.
    @Test func onlyIdempotentMethodsAreRepeated() {
        #expect(RetryMiddleware.isRepeatable(.get))
        #expect(RetryMiddleware.isRepeatable(.put))
        #expect(RetryMiddleware.isRepeatable(.delete))
        #expect(!RetryMiddleware.isRepeatable(.post))
        #expect(!RetryMiddleware.isRepeatable(.patch))
    }

    /// A refusal is a decision. Asking again gets the same answer and spends the user's
    /// time on a spinner.
    @Test func aRefusalIsNeverRetried() {
        let conflict = EngineFailure.refused(
            .init(status: 409, title: "ConflictError", detail: "already exists", fields: [])
        )
        #expect(!conflict.isTransient)

        let validation = EngineFailure.refused(
            .init(status: 422, title: "Unprocessable", detail: "", fields: [])
        )
        #expect(!validation.isTransient)
    }

    @Test func aDeadEngineAndAServerFaultAre() {
        #expect(EngineFailure.unreachable(underlying: "connection refused").isTransient)
        #expect(EngineFailure.refused(.init(status: 503, title: "Unavailable", detail: "", fields: [])).isTransient)
    }
}

/// That a field complaint survives the trip to a form.
struct FieldProblemTests {
    /// The engine sends a JSON Pointer; a form knows about input names.
    @Test func aPointerBecomesAFieldName() {
        #expect(EngineFailure.FieldProblem(pointer: "body/name", message: "x").fieldName == "name")
        #expect(EngineFailure.FieldProblem(pointer: "body/seats", message: "x").fieldName == "seats")
    }

    /// An index is not a field. `rows/14/capacity` complains about capacity, not about 14 —
    /// and a form that labelled an input "14" would be worse than one that said nothing.
    @Test func anIndexIsSkipped() {
        #expect(EngineFailure.FieldProblem(pointer: "rows/14/capacity", message: "x").fieldName == "capacity")
    }

    @Test func anEmptyPointerDegradesRatherThanCrashing() {
        #expect(EngineFailure.FieldProblem(pointer: "", message: "x").fieldName == "")
    }
}
