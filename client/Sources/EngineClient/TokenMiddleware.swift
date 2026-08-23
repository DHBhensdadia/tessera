import Foundation
import HTTPTypes
import OpenAPIRuntime

/// Puts the engine's per-launch token on every request.
///
/// The generator has no built-in notion of authentication — deliberately — and the
/// documented pattern is a middleware that injects the header. That is the right shape
/// here for a reason beyond convenience: there are 109 operations, and a token attached at
/// the call site would be 109 opportunities to forget one, each failing as a 401 that looks
/// like a permissions bug rather than a missing header.
///
/// The token is issued per engine launch, so it belongs to the client instance rather than
/// to the process — two open projects have two engines and two different tokens.
public struct TokenMiddleware: ClientMiddleware {
    private let token: String

    public init(token: String) {
        self.token = token
    }

    public func intercept(
        _ request: HTTPRequest,
        body: HTTPBody?,
        baseURL: URL,
        operationID: String,
        next: (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
    ) async throws -> (HTTPResponse, HTTPBody?) {
        var request = request
        request.headerFields[.tesseraToken] = token
        return try await next(request, body, baseURL)
    }
}

extension HTTPField.Name {
    /// Spelled once. The engine reads this exact header, and it is also declared in the
    /// OpenAPI document as the `TesseraToken` security scheme so the contract says so.
    static let tesseraToken = Self("x-tessera-token")!
}
