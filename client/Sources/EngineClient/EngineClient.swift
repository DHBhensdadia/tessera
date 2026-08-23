import Foundation
import OpenAPIRuntime
import OpenAPIURLSession

/// A typed connection to one running engine.
///
/// `Client` itself is generated from `openapi.json` at build time — all 109 operations and
/// 114 models — so the set of things callable from Swift is *derived* from the contract
/// rather than maintained alongside it. A route that disappears from the engine disappears
/// from this type, and the code that called it stops compiling. That is the strongest form
/// the phase's "contract drift fails a test" can take: not a test, a build failure.
///
/// One instance per engine, because the port and the token are per engine (2.9's rule that
/// one engine serves one project for its whole life).
public struct EngineConnection: Sendable {
    /// The generated client. Public because every screen from 3.4 calls it directly —
    /// wrapping 109 operations in hand-written passthroughs would reintroduce exactly the
    /// hand-maintained layer that generating the client removes.
    public let client: Client

    public init(port: Int, token: String, session: URLSession = .shared) {
        // The origin only. The document declares no `servers` entry and its paths are
        // absolute — `/api/v1/institutions` — so a base URL carrying the prefix produces
        // `/api/v1/api/v1/institutions`, which the engine answers with a well-formed 404
        // that decodes perfectly and means nothing. Found by making a real call; a
        // compiling client proves the shape of a request, never its address.
        //
        // The engine binds loopback and nothing else; the host is not configurable because
        // making it so would be the first step toward putting an institution's staffing
        // data on a network interface.
        let base = URL(string: "http://127.0.0.1:\(port)")!
        client = Client(
            serverURL: base,
            transport: URLSessionTransport(configuration: .init(session: session)),
            middlewares: [TokenMiddleware(token: token)]
        )
    }
}
