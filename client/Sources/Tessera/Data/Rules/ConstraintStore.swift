import DesignSystem
import EngineClient
import Observation

/// How strongly a preference pulls, in the words P7 uses and the number the model stores.
///
/// The model stores an integer; P7 draws low / medium / high. Both have to be the same fact,
/// or a weight set in the console reads as something else natively — so the mapping is
/// written once, here, and derived in one direction only.
///
/// **The number is authoritative.** Three buckets that wrote back a canonical value would
/// silently rewrite a 5 into a 4 the first time somebody opened a project the console had
/// touched, which is a data change disguised as a rendering.
enum WeightScale {
    /// What the engine accepts. `weight` is `ge=0`, but 0 on an enabled soft constraint
    /// means "costs nothing", which is what `enabled` is for and says more clearly.
    static let range = 1...10

    static func word(for weight: Int) -> String {
        switch weight {
        case ..<4: "low"
        case ..<7: "medium"
        default: "high"
        }
    }

    /// The seeded defaults span 1–8, so every word is reachable from a fresh project and
    /// nobody has to discover the top of the range by dragging.
    static func caption(for weight: Int) -> String { word(for: weight) }
}

/// The constraints of one term, and the catalogue describing what they could be.
///
/// Term-scoped, like availability and unlike everything else on the data screens: the same
/// department may want gaps minimised hard in the semester its first-years arrive and not
/// in the next, and the engine models that by hanging the rows off the term.
@Observable
@MainActor
final class ConstraintStore {
    private let connection: EngineConnection
    private let term: Int

    /// What cannot be switched off. Fetched from the engine rather than written here, so the
    /// client is not the authoritative statement of Tessera's hard rules.
    private(set) var invariants: [Invariant] = []
    /// Term-wide preferences: the `global` scope, weighted.
    private(set) var preferences: [Preference] = []
    var notice: String?

    struct Invariant: Identifiable, Sendable, Hashable {
        let id: String
        let statement: String
        let because: String
    }

    struct Preference: Identifiable, Sendable, Hashable {
        let id: Int
        /// The engine's own sentence. Not assembled here — `ConstraintSpec` carries the
        /// summary precisely so there is one copy of it.
        let summary: String
        var weight: Int
        var enabled: Bool
        /// A `global` kind that names targets is that preference narrowed to them. The
        /// screen has to say so, because a slider that silently means "everybody" is a
        /// different promise from one that means "these three people".
        let narrowedTo: Int
    }

    init(connection: EngineConnection, term: Int) {
        self.connection = connection
        self.term = term
    }

    func load() async {
        do {
            if invariants.isEmpty {
                // Once per store: the catalogue describes the build, not the file.
                invariants = try await connection.run {
                    try await $0.constraintCatalogue().ok.body.json
                }.invariants.map {
                    Invariant(id: $0.key, statement: $0.statement, because: $0.because)
                }
            }
            preferences = try await connection.run {
                try await $0.listConstraints(path: .init(term_id: term)).ok.body.json
            }.items
                .filter { $0.scope == .global }
                .map {
                    Preference(
                        id: $0.id,
                        summary: $0.summary,
                        weight: $0.weight,
                        enabled: $0.enabled,
                        narrowedTo: ($0.targets ?? []).count
                    )
                }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    /// Move a weight.
    ///
    /// Applied locally first so the control follows the pointer, and rolled back if the
    /// engine refuses. A slider that waits for a round trip before moving feels broken; one
    /// that moves and then lies is worse.
    func setWeight(_ weight: Int, on preference: Preference) async {
        var changes = Components.Schemas.ConstraintUpdate()
        changes.weight = weight
        await change(preference, to: changes) { $0.weight = weight }
    }

    /// Disable a preference without deleting it.
    ///
    /// Three different things live on a constraint — whether it is considered at all
    /// (`enabled`), whether it must hold or is costed (`is_hard`), and what a violation
    /// costs (`weight`). Deleting a preference to silence it loses the weight somebody
    /// tuned; setting the weight to zero says "costs nothing", which is not the same
    /// sentence as "do not consider this".
    func setEnabled(_ enabled: Bool, on preference: Preference) async {
        var changes = Components.Schemas.ConstraintUpdate()
        changes.enabled = enabled
        await change(preference, to: changes) { $0.enabled = enabled }
    }

    /// The optimistic edit, once, for both of them.
    ///
    /// The body is built by the caller and passed as a value rather than as a closure: a
    /// closure would be captured into the sendable one `run` takes, which Swift 6 refuses
    /// for a main-actor value — correctly, since nothing here needs to run over there.
    private func change(
        _ preference: Preference,
        to changes: Components.Schemas.ConstraintUpdate,
        applying local: (inout Preference) -> Void
    ) async {
        guard let index = preferences.firstIndex(where: { $0.id == preference.id }) else { return }
        notice = nil
        let previous = preferences[index]
        local(&preferences[index])
        do {
            _ = try await connection.run {
                try await $0.updateConstraint(
                    path: .init(constraint_id: preference.id), body: .json(changes)
                ).ok
            }
        } catch {
            preferences[index] = previous
            notice = EngineFailure.unwrap(error).message
        }
    }
}
