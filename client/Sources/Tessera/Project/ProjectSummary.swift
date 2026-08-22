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
    private(set) var terms: [EngineAPI.Term] = []
    private(set) var selectedTerm: EngineAPI.Term?

    func count(_ entity: Entity) -> Int? { counts[entity] }

    /// Load what the sidebar needs, tolerating partial failure.
    ///
    /// A count that does not arrive leaves its entry nil and the sidebar shows nothing
    /// beside that row, which is the honest rendering. Failing the whole load because one
    /// endpoint was slow would blank a sidebar that is otherwise correct.
    func load(from api: EngineAPI) async {
        terms = (try? await api.listTerms()) ?? []
        if selectedTerm == nil { selectedTerm = terms.first }

        for entity in Entity.allCases {
            if entity.isTermScoped {
                guard let term = selectedTerm else { continue }
                counts[entity] = try? await api.count(path: "terms/\(term.id)/\(entity.path)")
            } else {
                counts[entity] = try? await api.count(path: entity.path)
            }
        }
    }

    func select(_ term: EngineAPI.Term) {
        selectedTerm = term
    }
}
