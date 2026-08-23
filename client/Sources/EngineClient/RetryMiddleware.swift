import Foundation
import HTTPTypes
import OpenAPIRuntime

/// Retries the requests it is safe to retry, and no others.
///
/// **Never POST.** A create that times out after the engine wrote the row is
/// indistinguishable, from here, from one that never arrived — and retrying it produces a
/// second room with the same name. GET, PUT and DELETE are idempotent by definition: asking
/// again gets the same answer or the same end state.
///
/// Two attempts after the first, backing off from 100 ms. The engine is a subprocess on
/// loopback: it either answers immediately or it is gone, and a longer ladder only delays
/// telling the user something is wrong while a spinner turns.
public struct RetryMiddleware: ClientMiddleware {
    public static let attempts = 3
    public static let firstDelay = Duration.milliseconds(100)

    private let attempts: Int
    private let firstDelay: Duration

    public init(attempts: Int = RetryMiddleware.attempts, firstDelay: Duration = RetryMiddleware.firstDelay) {
        self.attempts = attempts
        self.firstDelay = firstDelay
    }

    /// Whether asking again is safe. Deliberately a method rather than a set, so the
    /// reasoning sits next to the rule.
    public static func isRepeatable(_ method: HTTPRequest.Method) -> Bool {
        switch method {
        case .get, .head, .put, .delete, .options: true
        default: false
        }
    }

    public func intercept(
        _ request: HTTPRequest,
        body: HTTPBody?,
        baseURL: URL,
        operationID: String,
        next: (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        guard Self.isRepeatable(request.method) else {
            return try await next(request, body, baseURL)
        }

        var delay = firstDelay
        for attempt in 1...attempts {
            do {
                return try await next(request, body, baseURL)
            } catch let failure as EngineFailure where failure.isTransient && attempt < attempts {
                try await Task.sleep(for: delay)
                delay *= 2
            } catch let error where !(error is EngineFailure) && attempt < attempts {
                // A transport error before `ProblemMiddleware` has mapped it. Ordering the
                // middlewares differently would avoid this branch, and would also mean
                // retrying *after* a refusal had already been turned into a decision.
                try await Task.sleep(for: delay)
                delay *= 2
            }
        }
        // The loop either returned or exhausted its attempts; the last one runs unguarded
        // so its failure is the one the caller sees, rather than a synthesised summary.
        return try await next(request, body, baseURL)
    }
}
