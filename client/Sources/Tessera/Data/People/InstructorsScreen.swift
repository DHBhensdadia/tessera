import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Instructors, and the first entity whose fields can be *absent* rather than empty.
///
/// A room's capacity is a number; an instructor's three load limits are a number **or no
/// limit at all**, which is a different thing from zero and the reason `NumberEntry`
/// exists. "At most 0 slots per day" is an instructor who cannot teach.
struct InstructorsScreen: View {
    let appearance: Appearance

    @State private var store: InstructorStore
    @State private var availability: AvailabilityStore?

    init(connection: EngineConnection, term: Int?, appearance: Appearance) {
        self.appearance = appearance
        _store = State(initialValue: InstructorStore(connection: connection))
        _availability = State(
            initialValue: term.map {
                AvailabilityStore(connection: connection, kind: .instructor, term: $0)
            }
        )
    }

    var body: some View {
        EntityWorkspace(
            title: "Instructors",
            items: store.instructors,
            label: \.name,
            value: { $0.maxSlotsPerWeek.map { "≤ \($0)/wk" } },
            detail: { instructor in
                InstructorDetail(
                    instructor: instructor,
                    store: store,
                    availability: availability,
                    appearance: appearance
                )
            },
            adding: .blank { Task { await store.add() } },
            delete: { instructor in Task { await store.delete(instructor) } },
            deleteWarning: "Any sessions this person teaches lose their instructor.",
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
final class InstructorStore {
    private let connection: EngineConnection

    private(set) var instructors: [Instructor] = []
    var selection: Instructor.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()

    static let editableFields: Set<String> = [
        "name", "email", "department_id",
        "max_slots_per_day", "max_slots_per_week", "max_consecutive_slots",
    ]

    private(set) var departments: [Chooser.Option] = []

    struct Instructor: Identifiable, Sendable, Hashable {
        let id: Int
        var name: String
        var email: String
        var departmentID: Int?
        /// All three nil-able, and nil is a value: *no limit*. Never defaulted to zero on
        /// the way in or out.
        var maxSlotsPerDay: Int?
        var maxSlotsPerWeek: Int?
        var maxConsecutiveSlots: Int?
    }

    init(connection: EngineConnection) {
        self.connection = connection
    }

    func load() async {
        do {
            let page = try await connection.run { try await $0.listInstructors().ok.body.json }
            instructors = page.items.map(Self.make)
            if selection == nil { selection = instructors.first?.id }

            departments = try await connection.run { try await $0.listDepartments().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    private static func make(_ read: Components.Schemas.InstructorRead) -> Instructor {
        Instructor(
            id: read.id,
            name: read.name,
            email: read.email,
            departmentID: read.department?.id,
            maxSlotsPerDay: read.max_slots_per_day,
            maxSlotsPerWeek: read.max_slots_per_week,
            maxConsecutiveSlots: read.max_consecutive_slots
        )
    }

    func add() async {
        forgetLastRefusal()
        do {
            let created = try await connection.run {
                try await $0.createInstructor(body: .json(.init(name: uniqueName()))).created.body.json
            }
            instructors.append(Self.make(created))
            selection = created.id
        } catch {
            report(error)
        }
    }

    func save(_ instructor: Instructor) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var changes = Components.Schemas.InstructorUpdate()
                changes.name = instructor.name
                changes.email = instructor.email
                changes.department_id = instructor.departmentID
                changes.max_slots_per_day = instructor.maxSlotsPerDay
                changes.max_slots_per_week = instructor.maxSlotsPerWeek
                changes.max_consecutive_slots = instructor.maxConsecutiveSlots
                return try await $0.updateInstructor(
                    path: .init(instructor_id: instructor.id), body: .json(changes)
                ).ok
            }
            fieldErrors = FieldErrors()
            notice = nil
            if let index = instructors.firstIndex(where: { $0.id == instructor.id }) {
                instructors[index] = instructor
            }
        } catch {
            report(error)
        }
    }

    func delete(_ instructor: Instructor) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                try await $0.deleteInstructor(path: .init(instructor_id: instructor.id))
            }
            instructors.removeAll { $0.id == instructor.id }
            if selection == instructor.id { selection = instructors.first?.id }
        } catch {
            report(error)
        }
    }

    func message(for field: String) -> String? { fieldErrors.message(for: field) }

    /// A complaint this form raised itself, about text that is not a number.
    ///
    /// Kept apart from `fieldErrors`, which belong to the engine: this one never left the
    /// machine, and clearing it on the next request would be wrong — the request was never
    /// made.
    var localProblems: [String: String] = [:]

    func complain(_ message: String?, about field: String) {
        localProblems[field] = message
    }

    func problem(for field: String) -> String? {
        localProblems[field] ?? message(for: field)
    }

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
        var candidate = "New Instructor"
        var suffix = 2
        while instructors.contains(where: { $0.name == candidate }) {
            candidate = "New Instructor \(suffix)"
            suffix += 1
        }
        return candidate
    }
}
