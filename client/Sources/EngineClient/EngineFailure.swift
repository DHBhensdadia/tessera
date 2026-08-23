import Foundation
import OpenAPIRuntime

/// Why a request did not succeed, in the terms a screen has to answer in.
///
/// The engine answers RFC 9457 Problem Details, and this keeps that structure all the way
/// to the view. 3.2's hand-written seed did the opposite and said so in a comment: it kept
/// the body as an unparsed string, because a tidier message would have thrown away the only
/// description of what actually went wrong.
///
/// The distinction that matters for 3.4: a **422 is a field error**. "That is not a number
/// of seats" belongs beside the seats field, and a form cannot put it there from a string.
/// A **409 is a rule violation** with a sentence the engine already wrote — "deleting this
/// group would remove 3 sub-groups" — and re-wording it in Swift would give the application
/// two vocabularies for one refusal.
public enum EngineFailure: Error, Sendable {
    /// The engine refused, and said why in the way it always does.
    case refused(Problem)
    /// The engine is not answering — it died, or never came up.
    case unreachable(underlying: String)

    /// One RFC 9457 document.
    public struct Problem: Sendable, Hashable {
        public let status: Int
        /// Short and constant per kind — "Conflict", "Unprocessable Entity".
        public let title: String
        /// About *this* occurrence, and the part worth showing a person.
        public let detail: String
        /// Which field, when the engine knows. Empty for failures that are not about a
        /// field, which is most of them.
        public let fields: [FieldProblem]

        public init(status: Int, title: String, detail: String, fields: [FieldProblem]) {
            self.status = status
            self.title = title
            self.detail = detail
            self.fields = fields
        }
    }

    /// A complaint about one field of a submitted payload.
    public struct FieldProblem: Sendable, Hashable {
        /// A JSON Pointer, as the engine sends it — `body/name`, `rows/14/capacity`.
        public let pointer: String
        public let message: String
        /// A suggested correction, where the engine has one. Often empty.
        public let hint: String

        public init(pointer: String, message: String, hint: String = "") {
            self.pointer = pointer
            self.message = message
            self.hint = hint
        }

        /// The last component, which is what a form labels its inputs with.
        ///
        /// A pointer is `body/name` or `rows/14/capacity`; a form knows about `name` and
        /// `capacity`. Anything numeric is an index rather than a field, so it is skipped —
        /// `rows/14/capacity` is a complaint about capacity, not about 14.
        public var fieldName: String {
            pointer.split(separator: "/").last(where: { Int($0) == nil }).map(String.init) ?? pointer
        }
    }

    // MARK: - What a screen asks

    public var problem: Problem? {
        if case .refused(let problem) = self { return problem }
        return nil
    }

    /// Field-level complaints, if this refusal was about the payload.
    public var fields: [FieldProblem] { problem?.fields ?? [] }

    /// The message to show when there is nowhere better to put it.
    ///
    /// The unreachable case says one sentence rather than the chain URLSession produces.
    /// The first version interpolated `localizedDescription` from the wrapped `ClientError`
    /// and rendered eleven lines of `NSURLErrorDomain` internals, session task identifiers
    /// and CFNetwork codes — accurate, and not something to show anybody. The detail is
    /// still on the case for a log.
    public var message: String {
        switch self {
        case .refused(let problem):
            problem.detail.isEmpty ? problem.title : problem.detail
        case .unreachable:
            "The engine stopped responding."
        }
    }

    /// Whether retrying could plausibly help. A refusal is a decision, not a hiccup —
    /// asking again gets the same answer and wastes the user's time looking at a spinner.
    public var isTransient: Bool {
        switch self {
        case .unreachable: true
        case .refused(let problem): problem.status >= 500
        }
    }
}

extension EngineFailure {
    /// Dig the typed failure out of whatever the generated client wrapped it in.
    ///
    /// A middleware that throws does not throw to the caller: `Client` catches it and
    /// rethrows a `ClientError` carrying the request, the input, the operation id and the
    /// original as `underlyingError`. So `catch let failure as EngineFailure` never matches,
    /// and every call site would instead see a paragraph of diagnostics with the useful
    /// sentence buried three levels inside it.
    ///
    /// Found by running the thing, not by reading it: the middleware was producing exactly
    /// the right value — `409 ConflictError, "a building called 'Block A' already exists
    /// here"` — and the probe still fell through to its generic handler.
    public static func unwrap(_ error: any Error) -> EngineFailure {
        if let failure = error as? EngineFailure { return failure }
        if let client = error as? ClientError {
            return unwrap(client.underlyingError)
        }
        return .unreachable(underlying: error.localizedDescription)
    }
}

extension EngineConnection {
    /// Make a call and get either the value or an `EngineFailure`.
    ///
    /// Two jobs, both of which every one of 3.4's screens would otherwise repeat: unwrap
    /// the `ClientError` the generated code wraps middleware failures in, and give the
    /// call site one `catch` that means something.
    ///
    /// It deliberately does **not** wrap the 109 operations. The closure receives the
    /// generated client and calls it directly, so the typed surface stays the generated
    /// one — a facade with 109 hand-written passthroughs is exactly the maintained layer
    /// that generating the client removes.
    public func run<T: Sendable>(
        _ work: sending (Client) async throws -> T
    ) async throws -> T {
        do {
            return try await work(client)
        } catch {
            throw EngineFailure.unwrap(error)
        }
    }
}
