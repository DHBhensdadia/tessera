import EngineClient
import Foundation
import Observation

/// How much of a project actually exists yet.
///
/// The sidebar shows these beside each section, which turns a navigator into a
/// completeness indicator — P7 Act 3's phrase, and the reason the counts are worth a
/// request rather than being left until each screen loads its own.
///
/// Every count is optional and starts nil. **Nil is not zero**: "we have not asked yet"
/// and "there are none" look identical if both render as `0`, and the second one is a
/// prompt to do something while the first is a spinner that finished too early.
@Observable
@MainActor
final class ProjectSummary {
    enum Entity: String, CaseIterable, Sendable {
        case rooms, instructors, courses, groups, constraints

        /// The endpoint that answers with a `Page`, whose `total` is the count.
        var path: String {
            switch self {
            case .rooms: "rooms"
            case .instructors: "instructors"
            case .courses: "courses"
            case .groups: "student-groups"
            case .constraints: "constraints"
            }
        }

        /// Constraints belong to a term; everything else belongs to the institution.
        var isTermScoped: Bool { self == .constraints }
    }

    private(set) var counts: [Entity: Int] = [:]
    private(set) var terms: [Term] = []
    private(set) var selectedTerm: Term?

    /// The generated model, named locally so the views do not each spell out where it
    /// comes from. One `typealias` rather than a wrapper struct: a hand-written mirror of
    /// a generated type is a second definition that has to be kept in step by hand.
    typealias Term = Components.Schemas.TermRead

    func count(_ entity: Entity) -> Int? { counts[entity] }

    /// Load what the sidebar needs, tolerating partial failure.
    ///
    /// A count that does not arrive leaves its entry nil and the sidebar shows nothing
    /// beside that row, which is the honest rendering. Failing the whole load because one
    /// endpoint was slow would blank a sidebar that is otherwise correct.
    func load(from connection: EngineConnection) async {
        terms = (try? await connection.run { try await $0.listTerms(.init()).ok.body.json.items }) ?? []
        if selectedTerm == nil { selectedTerm = terms.first }

        for entity in Entity.allCases {
            counts[entity] = await count(entity, using: connection)
        }
    }

    /// One count, or nil if it did not arrive.
    ///
    /// Each is asked for separately and a failure leaves its entry nil, which the sidebar
    /// draws as nothing rather than as zero. Failing the whole load because one endpoint
    /// was slow would blank a sidebar that is otherwise correct.
    ///
    /// **This downloads every row to count them, and there is no way not to.** The engine
    /// has no pagination: `Page` carries `items` and `total`, and no route accepts `limit`
    /// or `offset`. 3.2's hand-written client sent `?limit=1` and a comment claiming this
    /// was "one request rather than a download of every row" — FastAPI ignored the unknown
    /// parameter and the claim was never true. The generated client cannot send it at all,
    /// which is how the falsehood surfaced.
    ///
    /// Acceptable now, at a department's scale. Not at P1's ceiling of 5,000 sessions and
    /// 1,000 instructors, where a sidebar would drag the whole database across loopback on
    /// every window open. Pagination is in the backlog as an engine change.
    private func count(_ entity: Entity, using connection: EngineConnection) async -> Int? {
        // Constraints hang off a term; without one there is nothing to count, which is a
        // different answer from zero and is why this returns before asking.
        if entity.isTermScoped, selectedTerm == nil { return nil }
        let term = selectedTerm?.id
        return try? await connection.run { client -> Int in
            switch entity {
            case .rooms: try await client.listRooms(.init()).ok.body.json.total
            case .instructors: try await client.listInstructors(.init()).ok.body.json.total
            case .courses: try await client.listCourses(.init()).ok.body.json.total
            case .groups: try await client.listGroups(.init()).ok.body.json.total
            case .constraints:
                try await client.listConstraints(
                    .init(path: .init(term_id: term ?? 0))
                ).ok.body.json.total
            }
        }
    }

    func select(_ term: Term) {
        selectedTerm = term
    }
}
