import Foundation

/// The engine's HTTP surface, as far as the shell needs it.
///
/// **A seed, and named as one.** 3.3 owns the typed client for all of the engine's
/// endpoints, checked against the OpenAPI snapshot so contract drift fails a test. This
/// covers the four calls the shell cannot do without: health, and the three POSTs that
/// turn an empty database into a project somebody can use.
///
/// The alternative was to stub project creation until 3.3, which would have meant building
/// the welcome window against a fake and then building it again. This is the smaller lie —
/// and it is a lie only in scope, not in shape: 3.3 extends this type rather than replacing
/// it, which is why the request plumbing is generic and only the endpoints are specific.
///
/// Every request carries the per-launch token. The engine binds loopback and refuses
/// anything unauthenticated, so a missing header is a 401 rather than a silent success.
struct EngineAPI: Sendable {
    let port: Int
    let token: String

    private var base: URL { URL(string: "http://127.0.0.1:\(port)/api/v1")! }

    // MARK: - Wire types
    //
    // Named for the schema they mirror, so a mismatch with `docs/openapi.json` is visible
    // by reading rather than by running. Snake case is the wire's, not ours: the decoder
    // converts, and the Swift side keeps Swift spelling.

    struct Institution: Codable, Sendable {
        let id: Int
        let name: String
    }

    struct TimeGrid: Codable, Sendable {
        let id: Int
        let name: String
        let days: Int
        let slotsPerDay: Int
        let slotMinutes: Int
        let dayStartMinute: Int
        let breakSlots: [Int]
        let slotCount: Int
    }

    struct Term: Codable, Sendable {
        let id: Int
        let name: String
        let academicYear: String
    }

    // MARK: - The four calls the shell makes

    func createInstitution(name: String) async throws -> Institution {
        try await post("institutions", ["name": name])
    }

    func createTimeGrid(
        institution: Int,
        days: Int,
        slotsPerDay: Int,
        slotMinutes: Int,
        dayStartMinute: Int,
        breakSlots: [Int]
    ) async throws -> TimeGrid {
        try await post(
            "time-grids",
            [
                "institution_id": institution,
                "days": days,
                "slots_per_day": slotsPerDay,
                "slot_minutes": slotMinutes,
                "day_start_minute": dayStartMinute,
                "break_slots": breakSlots,
            ]
        )
    }

    func createTerm(
        institution: Int,
        timeGrid: Int,
        academicYear: String,
        name: String
    ) async throws -> Term {
        try await post(
            "terms",
            [
                "institution_id": institution,
                "time_grid_id": timeGrid,
                "academic_year": academicYear,
                "name": name,
            ]
        )
    }

    // MARK: - Plumbing

    private func post<Response: Decodable>(
        _ path: String,
        _ body: [String: Any]
    ) async throws -> Response {
        var request = URLRequest(url: base.appending(path: path))
        request.httpMethod = "POST"
        request.setValue(token, forHTTPHeaderField: "x-tessera-token")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw APIError(status: status, body: String(decoding: data, as: UTF8.self))
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Response.self, from: data)
    }
}

/// What the engine said when it refused.
///
/// The body is kept whole rather than parsed. The engine answers in RFC 9457 Problem
/// Details, and 3.3 will decode that properly; throwing away the detail here in order to
/// show a tidier message would discard the only description of what actually went wrong.
struct APIError: Error, CustomStringConvertible {
    let status: Int
    let body: String

    var description: String {
        "The engine refused the request (\(status)). \(body)"
    }
}
