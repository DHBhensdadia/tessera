import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Rooms, and the first screen anybody can actually use.
///
/// It is deliberately the first: a room has a name, a number, and two relationships, which
/// is enough variety to find out whether `EntityWorkspace` fits before seven more screens
/// depend on it, and little enough that the answer arrives quickly.
struct RoomsScreen: View {
    let connection: EngineConnection
    /// Availability belongs to a term, and nothing else on this screen does. Nil means no
    /// term is selected, and the grid says so rather than drawing an empty week.
    let term: Int?
    let appearance: Appearance

    @State private var store: RoomStore
    @State private var availability: AvailabilityStore?

    init(connection: EngineConnection, term: Int?, appearance: Appearance) {
        self.connection = connection
        self.term = term
        self.appearance = appearance
        _store = State(initialValue: RoomStore(connection: connection))
        _availability = State(
            initialValue: term.map { AvailabilityStore(connection: connection, kind: .room, term: $0) }
        )
    }

    /// A screen around a store that has already loaded.
    ///
    /// For `--render`, as `ConstraintsScreen` has one: `ImageRenderer` has no run loop, so
    /// `.task` never fires and a screen that loads itself draws its empty state.
    init(loaded store: RoomStore, availability: AvailabilityStore?, appearance: Appearance) {
        self.connection = store.connection
        self.term = 0
        self.appearance = appearance
        _store = State(initialValue: store)
        _availability = State(initialValue: availability)
    }

    var body: some View {
        EntityWorkspace(
            title: "Rooms",
            items: store.rooms,
            label: \.name,
            value: { "\($0.capacity)" },
            detail: { room in
                RoomDetail(
                    room: room,
                    store: store,
                    availability: availability,
                    appearance: appearance
                )
            },
            adding: .blank { Task { await store.add() } },
            delete: { room in Task { await store.delete(room) } },
            deleteWarning: "Any sessions already placed in this room lose their room.",
            selection: $store.selection,
            notice: store.notice,
            dismissNotice: { store.notice = nil },
            appearance: appearance
        )
        .task { await store.load() }
    }
}

/// What the rooms screen knows, and every request it makes.
///
/// Separate from the view because a screen that owns its own networking cannot be reasoned
/// about without a window, and because the same shape will be copied seven more times —
/// better that it be a shape worth copying.
@Observable
@MainActor
final class RoomStore {
    let connection: EngineConnection

    private(set) var rooms: [Room] = []
    var selection: Room.ID?
    /// A refusal with nowhere better to go. Never dropped — see `FieldErrors`.
    var notice: String?
    private(set) var fieldErrors = FieldErrors()

    /// The fields this form has. Used to decide whether a complaint from the engine has
    /// somewhere to land, rather than assuming it does.
    static let editableFields: Set<String> = ["name", "capacity", "building_id", "feature_ids"]

    /// What a room can be given, fetched alongside the rooms themselves.
    ///
    /// Loaded here rather than by the detail view: a picker that fetches its own options
    /// refetches them every time the selection changes, and a room list of forty would ask
    /// for the building list forty times.
    private(set) var buildings: [Chooser.Option] = []
    private(set) var features: [Chooser.Option] = []

    struct Room: Identifiable, Sendable, Hashable {
        let id: Int
        var name: String
        var capacity: Int
        var buildingID: Int?
        var featureIDs: Set<Int>
    }

    init(connection: EngineConnection) {
        self.connection = connection
    }

    func load() async {
        do {
            let page = try await connection.run { try await $0.listRooms().ok.body.json }
            rooms = page.items.map {
                Room(
                    id: $0.id,
                    name: $0.name,
                    capacity: $0.capacity,
                    buildingID: $0.building?.id,
                    featureIDs: Set(($0.features ?? []).map(\.id))
                )
            }
            if selection == nil { selection = rooms.first?.id }

            buildings = try await connection.run { try await $0.listBuildings().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
            features = try await connection.run { try await $0.listFeatures().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    func add() async {
        forgetLastRefusal()
        // A name the engine will accept and the user will immediately replace. Creating
        // with an empty name would be refused, which turns "Add" into an error message.
        let name = uniqueName()
        do {
            let created = try await connection.run {
                try await $0.createRoom(body: .json(.init(capacity: 30, name: name))).created.body.json
            }
            rooms.append(
                Room(
                    id: created.id,
                    name: created.name,
                    capacity: created.capacity,
                    buildingID: created.building?.id,
                    featureIDs: Set((created.features ?? []).map(\.id))
                )
            )
            selection = created.id
        } catch {
            report(error)
        }
    }

    /// Save one field, on commit rather than on keystroke (D3).
    ///
    /// A failure keeps what was typed. Reverting to the server's value would discard the
    /// user's work in order to look consistent, which is the wrong way round — they can
    /// see the message and fix it, and they cannot retype what they no longer have.
    func save(_ room: Room) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var changes = Components.Schemas.RoomUpdate()
                changes.name = room.name
                changes.capacity = room.capacity
                changes.building_id = room.buildingID
                changes.feature_ids = Array(room.featureIDs).sorted()
                return try await $0.updateRoom(path: .init(room_id: room.id), body: .json(changes)).ok
            }
            fieldErrors = FieldErrors()
            notice = nil
            if let index = rooms.firstIndex(where: { $0.id == room.id }) { rooms[index] = room }
        } catch {
            report(error)
        }
    }

    func delete(_ room: Room) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run { try await $0.deleteRoom(path: .init(room_id: room.id)) }
            rooms.removeAll { $0.id == room.id }
            if selection == room.id { selection = rooms.first?.id }
        } catch {
            // The engine refuses a delete that would orphan something (#48) and says what
            // still depends on it. That sentence is the whole value of the refusal.
            report(error)
        }
    }

    func message(for field: String) -> String? { fieldErrors.message(for: field) }

    /// Forget the last refusal before making a new request.
    ///
    /// Without this a message outlives the thing that caused it: rename a building and be
    /// refused, then delete it successfully, and the old complaint is still on screen
    /// attached to an operation that worked. Found by a probe reading `notice` after a
    /// delete and getting the rename's sentence — which also meant the probe could not tell
    /// whether the delete had been refused at all.
    private func forgetLastRefusal() {
        notice = nil
        fieldErrors = FieldErrors()
    }

    private func report(_ error: any Error) {
        let failure = EngineFailure.unwrap(error)
        fieldErrors = FieldErrors.from(failure, fields: Self.editableFields)
        notice = fieldErrors.unrouted.isEmpty ? nil : fieldErrors.unrouted.joined(separator: "\n")
    }

    private func uniqueName() -> String {
        var candidate = "New Room"
        var suffix = 2
        while rooms.contains(where: { $0.name == candidate }) {
            candidate = "New Room \(suffix)"
            suffix += 1
        }
        return candidate
    }
}
