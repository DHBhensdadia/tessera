import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Teaching weeks — how long a week is, and where the breaks fall.
///
/// **A grid cannot be edited, only made and removed.** That is #51 rather than a missing
/// endpoint: a `TimeGrid` is one repeating week and every session ever placed is an integer
/// index into it, so moving lunch by half an hour would silently move every lecture in every
/// timetable built on it. The engine offers GET, POST and DELETE and no PATCH, and this
/// screen says why rather than showing fields that cannot be saved.
///
/// The week is drawn rather than described. A row of numbers — *5 days, 8 slots, 60 minutes,
/// breaks {4}* — is the same information and nobody can see lunch in it.
struct GridsScreen: View {
    let appearance: Appearance

    @State private var store: GridStore

    init(connection: EngineConnection, appearance: Appearance) {
        self.appearance = appearance
        _store = State(initialValue: GridStore(connection: connection))
    }

    var body: some View {
        EntityWorkspace(
            title: "Teaching Weeks",
            items: store.grids,
            label: \.name,
            value: { "\($0.usableSlots) slots" },
            detail: { grid in
                GridDetail(grid: grid, appearance: appearance)
            },
            adding: .blank { Task { await store.add() } },
            delete: { grid in Task { await store.delete(grid) } },
            deleteWarning: "A week still used by a term will be refused, and Tessera will say which.",
            selection: $store.selection,
            notice: store.notice,
            dismissNotice: { store.notice = nil },
            appearance: appearance
        )
        .task { await store.load() }
    }
}

@Observable
@MainActor
final class GridStore {
    private let connection: EngineConnection

    private(set) var grids: [Grid] = []
    var selection: Grid.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()

    private var institution: Int?

    struct Grid: Identifiable, Sendable, Hashable {
        let id: Int
        let name: String
        let week: AvailabilityGrid.Week
        /// What can actually be taught in: the whole week, less the breaks. The number P7
        /// insists on stating out loud, because it is the one somebody is really choosing.
        var usableSlots: Int {
            week.days * (week.slotsPerDay - week.breakSlots.count)
        }
    }

    init(connection: EngineConnection) {
        self.connection = connection
    }

    func load() async {
        do {
            if institution == nil {
                institution = try await connection.run {
                    try await $0.listInstitutions().ok.body.json
                }.items.first?.id
            }
            grids = try await connection.run { try await $0.listTimeGrids().ok.body.json }
                .items.map {
                    Grid(
                        id: $0.id,
                        name: $0.name,
                        week: .init(
                            days: $0.days,
                            slotsPerDay: $0.slots_per_day,
                            slotMinutes: $0.slot_minutes,
                            dayStartMinute: $0.day_start_minute,
                            breakSlots: Set($0.break_slots ?? [])
                        )
                    )
                }
            if selection == nil { selection = grids.first?.id }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    /// A new week, on the shape the creation sheet defaults to.
    ///
    /// Nine to five, hourly, with an hour for lunch — the same defaults `TimeGridSetup`
    /// offers, because a person adding a second week almost always wants a variation on the
    /// first and typing seven numbers to get there is not an interface.
    func add() async {
        notice = nil
        guard let institution else {
            notice = "This project has no institution yet, so a teaching week has nothing to belong to."
            return
        }
        let name = uniqueName()
        do {
            _ = try await connection.run {
                var body = Components.Schemas.TimeGridCreate(
                    day_start_minute: 9 * 60,
                    days: 5,
                    institution_id: institution,
                    slot_minutes: 60,
                    slots_per_day: 8
                )
                body.name = name
                body.break_slots = [4]
                return try await $0.createTimeGrid(body: .json(body)).created
            }
            await load()
            selection = grids.first { $0.name == name }?.id ?? selection
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    func delete(_ grid: Grid) async {
        notice = nil
        do {
            _ = try await connection.run { try await $0.deleteTimeGrid(path: .init(grid_id: grid.id)) }
            grids.removeAll { $0.id == grid.id }
            if selection == grid.id { selection = grids.first?.id }
        } catch {
            // Refused while a term still uses it, with the engine's own sentence.
            notice = EngineFailure.unwrap(error).message
        }
    }

    private func uniqueName() -> String {
        var candidate = "New Week"
        var suffix = 2
        while grids.contains(where: { $0.name == candidate }) {
            candidate = "New Week \(suffix)"
            suffix += 1
        }
        return candidate
    }
}

/// One teaching week, drawn.
struct GridDetail: View {
    let grid: GridStore.Grid
    let appearance: Appearance

    private var summary: String {
        let week = grid.week
        let end = week.dayStartMinute + week.slotsPerDay * week.slotMinutes
        return "\(week.days) days, \(week.label(forSlotOfDay: 0)) to "
            + String(format: "%02d:%02d", (end / 60) % 24, end % 60)
            + ", in \(week.slotMinutes)-minute slots."
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Teaching week", appearance: appearance) {
                Text(grid.name)
                    .font(Typography.title.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                Text(summary)
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                // Naming the breaks only when there are some. "40 usable slots, once the
                // breaks are taken out" beside a week with no breaks is a sentence that
                // makes a reader go looking for something that is not there.
                Text(grid.week.breakSlots.isEmpty
                     ? "\(grid.usableSlots) slots a week, with no breaks set."
                     : "\(grid.usableSlots) usable slots a week, once the breaks are taken out.")
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                Text("A week cannot be changed once it exists. Every session ever placed is a "
                     + "number counted from its first slot, so moving one would move them all. "
                     + "Add another week instead.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }

            ContentSection("The week", showsRule: false, appearance: appearance) {
                AvailabilityGrid(
                    week: grid.week,
                    blocked: [],
                    editable: false,
                    appearance: appearance
                )
                if !grid.week.breakSlots.isEmpty {
                    Text("Hatched time is a break, and recurs on every day.")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                }
            }
        }
    }
}
