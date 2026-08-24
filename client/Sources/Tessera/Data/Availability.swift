import DesignSystem
import EngineClient
import Observation

/// The term's week, fetched once.
///
/// A term carries only a *reference* to its grid — an id and a name, which is what makes a
/// timetable render in one request rather than hundreds — so the shape of the week is two
/// hops away. Written here rather than in each screen because three of them need it and the
/// second copy was already half-written when this appeared.
enum TeachingWeek {
    static func load(
        _ connection: EngineConnection,
        term: Int
    ) async throws -> AvailabilityGrid.Week {
        let reference = try await connection.run {
            try await $0.getTerm(path: .init(term_id: term)).ok.body.json
        }.time_grid
        guard let reference else {
            // A term with no grid cannot happen through the application — the creation
            // sheet makes both — but it is reachable in a file somebody edited, and a
            // grid drawn from a guessed week would be worse than a sentence.
            throw EngineFailure.unreachable(underlying: "this term has no time grid")
        }
        let grid = try await connection.run {
            try await $0.getTimeGrid(path: .init(grid_id: reference.id)).ok.body.json
        }
        return AvailabilityGrid.Week(
            days: grid.days,
            slotsPerDay: grid.slots_per_day,
            slotMinutes: grid.slot_minutes,
            dayStartMinute: grid.day_start_minute,
            breakSlots: Set(grid.break_slots ?? [])
        )
    }
}

/// When a room or an instructor cannot be used, for one term.
///
/// One store for both, because the engine has one endpoint for both: `kind` is the only
/// difference, and it is a value rather than two nearly identical types (D5 — *build once,
/// use twice*).
///
/// Unavailability belongs to a **term**, unlike everything else on these two screens. A room
/// closed for refurbishment in Autumn is open again in Spring, and the engine models that by
/// hanging the rows off the term rather than the room.
@Observable
@MainActor
final class AvailabilityStore {
    typealias Kind = Components.Schemas.UnavailabilityKind

    private let connection: EngineConnection
    private let kind: Kind
    private let term: Int

    private(set) var week: AvailabilityGrid.Week?
    /// Week-absolute slots blocked for the subject currently shown.
    private(set) var blocked: Set<Int> = []
    private(set) var subject: Int?
    var notice: String?

    init(connection: EngineConnection, kind: Kind, term: Int) {
        self.connection = connection
        self.kind = kind
        self.term = term
    }

    /// Load the week once, and this subject's blocked slots every time.
    ///
    /// The week is the same for every room in the term, so refetching it per selection
    /// would be one request per click for an answer that cannot have changed.
    func load(subject id: Int) async {
        subject = id
        do {
            if week == nil { week = try await TeachingWeek.load(connection, term: term) }
            blocked = Set(
                try await connection.run {
                    try await $0.listUnavailability(
                        path: .init(term_id: term),
                        query: .init(kind: kind.rawValue, subject_id: id)
                    ).ok.body.json
                }.items.map(\.slot)
            )
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    /// One request per gesture, not per cell.
    ///
    /// The endpoint takes a list precisely because availability is edited by dragging: a
    /// drag across a morning is one intention, and sending eight requests for it would be
    /// eight chances to end up half-applied.
    func block(_ slots: Set<Int>) async {
        guard let subject, !slots.isEmpty else { return }
        notice = nil
        // Applied before the request and rolled back if it fails. The grid is a direct
        // manipulation — cells that stay pale until a round trip finishes make a drag feel
        // broken — but a refusal must not leave the screen claiming something the engine
        // does not hold.
        let previous = blocked
        blocked.formUnion(slots)
        do {
            _ = try await connection.run {
                try await $0.addUnavailability(
                    path: .init(term_id: term),
                    body: .json(.init(kind: kind, slots: Array(slots).sorted(), subject_id: subject))
                ).created
            }
        } catch {
            blocked = previous
            notice = EngineFailure.unwrap(error).message
        }
    }

    func free(_ slots: Set<Int>) async {
        guard let subject, !slots.isEmpty else { return }
        notice = nil
        let previous = blocked
        blocked.subtract(slots)
        do {
            // `slot` repeated frees exactly these; omitting it clears the subject entirely.
            // #45 added the filter for this screen, and passing the list is what keeps an
            // "unblock Tuesday morning" gesture from clearing the whole week.
            _ = try await connection.run {
                try await $0.clearUnavailability(
                    path: .init(term_id: term),
                    query: .init(
                        kind: kind.rawValue,
                        subject_id: subject,
                        slot: Array(slots).sorted()
                    )
                )
            }
        } catch {
            blocked = previous
            notice = EngineFailure.unwrap(error).message
        }
    }
}
