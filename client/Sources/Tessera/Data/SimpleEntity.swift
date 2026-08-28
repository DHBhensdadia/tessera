import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// The four entities that are a name and nothing else.
///
/// Buildings, features, departments and programs exist because the headline screens cannot
/// work without them — a room needs a building and features, an instructor needs a
/// department, a group needs a programme. The temptation is to hide them inside a picker's
/// "＋ New…" and never give them a screen.
///
/// They get real screens (D4) for three reasons: the console has them, so parity demands
/// it; a feature typed twice as "Projector" and "projector" is two capabilities and one
/// silent scheduling failure nobody can debug; and #43 added DELETE for buildings and
/// features specifically so a mistyped one need not be permanent.
///
/// One store serves all four. They differ only in which four operations they call, so the
/// difference is four closures rather than four types — and a bug in selection or error
/// routing is fixed once.
@Observable
@MainActor
final class SimpleEntityStore {
    struct Item: Identifiable, Sendable, Hashable {
        let id: Int
        var name: String
    }

    /// What one of these entities can do, as the four calls that differ.
    struct Operations: Sendable {
        let list: @Sendable (EngineConnection) async throws -> [Item]
        /// Takes the institution because three of the four belong to one, and the fourth
        /// ignores it. Passing it to all four is one honest signature; branching on which
        /// need it would put a fact about the engine's schema into four call sites.
        let create: @Sendable (EngineConnection, String, Int) async throws -> Item
        let rename: @Sendable (EngineConnection, Item) async throws -> Void
        let remove: @Sendable (EngineConnection, Int) async throws -> Void
    }

    let title: String
    /// What deleting one of these does. Per entity, because the answers genuinely differ.
    let deleteWarning: String
    private let connection: EngineConnection
    private let operations: Operations

    private(set) var items: [Item] = []
    /// The project's institution. There is exactly one — the creation sheet makes it — and
    /// everything below it needs its id to be created at all.
    private var institution: Int?
    var selection: Item.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()

    /// These forms have one field. Named anyway, so a complaint about anything else is
    /// reported rather than dropped.
    static let editableFields: Set<String> = ["name"]

    init(
        title: String,
        deleteWarning: String,
        connection: EngineConnection,
        operations: Operations
    ) {
        self.title = title
        self.deleteWarning = deleteWarning
        self.connection = connection
        self.operations = operations
    }

    func load() async {
        do {
            if institution == nil {
                institution = try await connection.run {
                    try await $0.listInstitutions().ok.body.json
                }.items.first?.id
            }
            items = try await operations.list(connection)
            if selection == nil { selection = items.first?.id }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    func add() async {
        forgetLastRefusal()
        guard let institution else {
            notice = "This project has no institution yet, so there is nothing to add to."
            return
        }
        do {
            let created = try await operations.create(connection, uniqueName(), institution)
            items.append(created)
            selection = created.id
        } catch {
            report(error)
        }
    }

    func save(_ item: Item) async {
        forgetLastRefusal()
        do {
            try await operations.rename(connection, item)
            fieldErrors = FieldErrors()
            notice = nil
            if let index = items.firstIndex(where: { $0.id == item.id }) { items[index] = item }
        } catch {
            report(error)
        }
    }

    func delete(_ item: Item) async {
        forgetLastRefusal()
        do {
            try await operations.remove(connection, item.id)
            items.removeAll { $0.id == item.id }
            if selection == item.id { selection = items.first?.id }
        } catch {
            // A building still holding rooms, or a feature a room requires, is refused with
            // a sentence naming the counts (#48). That sentence is the whole point.
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
        let base = "New \(title.dropLast(title.hasSuffix("s") ? 1 : 0))"
        var candidate = base
        var suffix = 2
        while items.contains(where: { $0.name == candidate }) {
            candidate = "\(base) \(suffix)"
            suffix += 1
        }
        return candidate
    }
}

/// One screen for any of the four.
///
/// The store is `@State` rather than a parameter, and that is not a style choice. Built by
/// the caller instead, it was **rebuilt on every body evaluation**: `load()` finished, set
/// `items`, which is observed, which re-ran `body`, which handed the view a brand-new empty
/// store — and `.task(id:)` did not re-fire because the title had not changed. The screen
/// then showed "No buildings yet" beside a sidebar counting two, indefinitely.
///
/// Switching destinations must still get a fresh store rather than buildings listed under
/// the heading "Features", which is what made a parameter look necessary. It is not:
/// `.id(title)` at the call site gives each destination its own view identity, and `@State`
/// belonging to a discarded identity is discarded with it.
struct SimpleEntityScreen: View {
    @State private var store: SimpleEntityStore
    let appearance: Appearance

    init(
        title: String,
        deleteWarning: String,
        connection: EngineConnection,
        operations: SimpleEntityStore.Operations,
        appearance: Appearance
    ) {
        _store = State(
            initialValue: SimpleEntityStore(
                title: title,
                deleteWarning: deleteWarning,
                connection: connection,
                operations: operations
            )
        )
        self.appearance = appearance
    }

    var body: some View {
        EntityWorkspace(
            title: store.title,
            items: store.items,
            label: \.name,
            value: { _ in nil },
            detail: { item in
                SimpleEntityDetail(item: item, store: store, appearance: appearance)
            },
            adding: .blank { Task { await store.add() } },
            delete: { item in Task { await store.delete(item) } },
            deleteWarning: store.deleteWarning,
            selection: Binding(get: { store.selection }, set: { store.selection = $0 }),
            notice: store.notice,
            dismissNotice: { store.notice = nil },
            appearance: appearance
        )
        .task { await store.load() }
    }
}

struct SimpleEntityDetail: View {
    let item: SimpleEntityStore.Item
    let store: SimpleEntityStore
    let appearance: Appearance

    @State private var name = ""

    var body: some View {
        ContentSection(store.title.dropLast(store.title.hasSuffix("s") ? 1 : 0).description,
                       appearance: appearance) {
            Field(
                label: "Name",
                value: $name,
                problem: store.message(for: "name"),
                appearance: appearance
            )
            .onSubmit {
                var edited = item
                edited.name = name
                Task { await store.save(edited) }
            }
            Text("Press return to save.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        }
        .task(id: item.id) { name = item.name }
    }
}
