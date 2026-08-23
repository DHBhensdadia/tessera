import Foundation
import HTTPTypes
import OpenAPIRuntime

/// Turns every refusal into an `EngineFailure`, once, for all 109 operations.
///
/// The generated client models each operation's failures as its own enum — 109 of them —
/// so without this, every call site would switch over a type that exists for that one
/// endpoint, and 3.4's forms would each re-derive "was this about a field?" from scratch.
///
/// A middleware is the only place that sees *every* response before the generated code
/// decodes it, which makes it the only place this can be done once.
///
/// **The body is read whole.** Problem Details are small and the alternative is guessing.
/// It would be the wrong choice for a streaming endpoint; the engine has none today, and
/// when Stage 5 streams solver progress this needs revisiting rather than extending.
public struct ProblemMiddleware: ClientMiddleware {
    public init() {}

    public func intercept(
        _ request: HTTPRequest,
        body: HTTPBody?,
        baseURL: URL,
        operationID: String,
        next: (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        let (response, responseBody) = try await withUnreachableMapped {
            try await next(request, body, baseURL)
        }

        guard response.status.code >= 400 else { return (response, responseBody) }

        // Collect once, then hand a fresh body onward — the generated decoder still needs
        // to read it for the failure cases it models itself.
        let collected: Data
        if let responseBody {
            collected = Data(try await ArraySlice(collecting: responseBody, upTo: 1 << 20))
        } else {
            collected = Data()
        }
        throw EngineFailure.refused(
            Problems.decode(collected, status: response.status.code, reason: response.status.reasonPhrase)
        )
    }

    /// A transport error means the engine is not there — a crash, a port that closed, a
    /// process that never started. It is not a refusal and must not be reported as one:
    /// "the engine stopped responding" and "that room name is taken" are different
    /// sentences with different remedies.
    private func withUnreachableMapped<T>(
        _ work: () async throws -> T
    ) async rethrows -> T {
        do {
            return try await work()
        } catch let failure as EngineFailure {
            throw failure
        } catch {
            throw EngineFailure.unreachable(underlying: error.localizedDescription)
        }
    }
}

/// Decoding one Problem document, tolerantly.
enum Problems {
    private struct Wire: Decodable {
        /// The engine's `ErrorDetail`: a JSON Pointer, a message, and sometimes a hint.
        ///
        /// The first version of this looked for a `field` key. There is no such key — the
        /// engine has always sent `pointer` — so every field-level complaint decoded to
        /// nothing and was dropped. A 422 arrived saying "1 field(s) failed validation"
        /// with no indication of *which*, which is precisely the case D5 exists for. The
        /// probe printed `NO FIELD DETAIL` and that is the only reason it was noticed.
        struct Detail: Decodable {
            let pointer: String?
            let message: String?
            let hint: String?
        }
        let status: Int?
        let title: String?
        let detail: String?
        let errors: [Detail]?
    }

    /// Falls back to the HTTP status rather than failing.
    ///
    /// A 502 from something that is not our engine, or a body that is not JSON at all, must
    /// still arrive as a usable failure — a decoder that throws while decoding an error
    /// replaces a bad message with no message.
    static func decode(_ data: Data, status: Int, reason: String) -> EngineFailure.Problem {
        guard let wire = try? JSONDecoder().decode(Wire.self, from: data) else {
            return .init(status: status, title: reason, detail: "", fields: [])
        }
        return .init(
            status: wire.status ?? status,
            title: wire.title ?? reason,
            detail: wire.detail ?? "",
            fields: (wire.errors ?? []).compactMap { detail in
                guard let message = detail.message else { return nil }
                return .init(
                    pointer: detail.pointer ?? "",
                    message: message,
                    hint: detail.hint ?? ""
                )
            }
        )
    }
}
