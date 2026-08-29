import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Courses — the catalogue, not the teaching.
///
/// A course is what a university *offers*; an offering is a course being taught in a
/// particular term, and sessions are what the solver places. That three-level split (#8) is
/// the model's shape and the reason this screen is short: everything about *when* and *to
/// whom* lives one level down, under Offerings.
struct CoursesScreen: View {
    let appearance: Appearance

    @State private var store: CourseStore

    init(connection: EngineConnection, appearance: Appearance) {
        self.appearance = appearance
        _store = State(initialValue: CourseStore(connection: connection))
    }

    /// A screen around a store that has already loaded.
    ///
    /// For `--render`, as `ConstraintsScreen` has one: `ImageRenderer` has no run loop, so
    /// `.task` never fires and a screen that loads itself draws its empty state.
    init(loaded store: CourseStore, appearance: Appearance) {
        self.appearance = appearance
        _store = State(initialValue: store)
    }

    var body: some View {
        EntityWorkspace(
            title: "Courses",
            items: store.courses,
            label: { "\($0.code) — \($0.name)" },
            value: { "\($0.credits) cr" },
            detail: { course in
                CourseDetail(course: course, store: store, appearance: appearance)
            },
            adding: .blank { Task { await store.add() } },
            delete: { course in Task { await store.delete(course) } },
            deleteWarning: "Everything this course is offered as, in every term, goes with it.",
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
final class CourseStore {
    private let connection: EngineConnection

    private(set) var courses: [Course] = []
    var selection: Course.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()
    var localProblems: [String: String] = [:]

    static let editableFields: Set<String> = ["code", "name", "credits", "department_id"]

    private(set) var departments: [Chooser.Option] = []

    struct Course: Identifiable, Sendable, Hashable {
        let id: Int
        var code: String
        var name: String
        var credits: Int
        var departmentID: Int?
    }

    init(connection: EngineConnection) {
        self.connection = connection
    }

    func load() async {
        do {
            let page = try await connection.run { try await $0.listCourses().ok.body.json }
            courses = page.items.map(Self.make)
            if selection == nil { selection = courses.first?.id }

            departments = try await connection.run { try await $0.listDepartments().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    private static func make(_ read: Components.Schemas.CourseRead) -> Course {
        Course(
            id: read.id,
            code: read.code,
            name: read.name,
            credits: read.credits,
            departmentID: read.department?.id
        )
    }

    func add() async {
        forgetLastRefusal()
        do {
            let created = try await connection.run {
                try await $0.createCourse(
                    body: .json(.init(code: uniqueCode(), name: "New Course"))
                ).created.body.json
            }
            courses.append(Self.make(created))
            selection = created.id
        } catch {
            report(error)
        }
    }

    func save(_ course: Course) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var changes = Components.Schemas.CourseUpdate()
                changes.code = course.code
                changes.name = course.name
                changes.credits = course.credits
                changes.department_id = course.departmentID
                return try await $0.updateCourse(
                    path: .init(course_id: course.id), body: .json(changes)
                ).ok
            }
            fieldErrors = FieldErrors()
            notice = nil
            if let index = courses.firstIndex(where: { $0.id == course.id }) { courses[index] = course }
        } catch {
            report(error)
        }
    }

    func delete(_ course: Course) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run { try await $0.deleteCourse(path: .init(course_id: course.id)) }
            courses.removeAll { $0.id == course.id }
            if selection == course.id { selection = courses.first?.id }
        } catch {
            report(error)
        }
    }

    func message(for field: String) -> String? { fieldErrors.message(for: field) }
    func complain(_ message: String?, about field: String) { localProblems[field] = message }
    func problem(for field: String) -> String? { localProblems[field] ?? message(for: field) }

    private func forgetLastRefusal() {
        notice = nil
        fieldErrors = FieldErrors()
    }

    private func report(_ error: any Error) {
        let failure = EngineFailure.unwrap(error)
        fieldErrors = FieldErrors.from(failure, fields: Self.editableFields)
        notice = fieldErrors.unrouted.isEmpty ? nil : fieldErrors.unrouted.joined(separator: "\n")
    }

    /// A code the engine will accept, which means one nothing else is using — course codes
    /// are unique, so "New Course" twice is a 409 rather than a second row.
    private func uniqueCode() -> String {
        var candidate = "NEW-101"
        var suffix = 2
        while courses.contains(where: { $0.code == candidate }) {
            candidate = "NEW-10\(suffix)"
            suffix += 1
        }
        return candidate
    }
}
