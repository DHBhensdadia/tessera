import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Offerings — a course being taught in a term, and the weekly pattern it repeats.
///
/// The first **term-scoped** screen. Everything before it belongs to the institution and is
/// true all year; an offering exists inside one term, which is why the toolbar's term
/// switcher stops being decoration here.
///
/// It is also the first screen where an item cannot be created blank. An offering *is* its
/// course — `OfferingCreate` takes one and there is no `PATCH /offerings` — so Add asks
/// which course rather than making a placeholder somebody would then be unable to change.
struct OfferingsScreen: View {
    let term: Int?
    let appearance: Appearance

    @State private var store: OfferingStore

    init(connection: EngineConnection, term: Int?, appearance: Appearance) {
        self.term = term
        self.appearance = appearance
        _store = State(initialValue: OfferingStore(connection: connection))
    }

    var body: some View {
        Group {
            if let term {
                EntityWorkspace(
                    title: "Offerings",
                    items: store.offerings,
                    label: { store.label(for: $0) },
                    value: { $0.sessionCount > 0 ? "\($0.sessionCount) sessions" : nil },
                    detail: { offering in
                        OfferingDetail(offering: offering, store: store, appearance: appearance)
                    },
                    adding: .choosing(
                        from: store.offerableCourses,
                        empty: store.courses.isEmpty
                            ? "No courses yet — add some first"
                            : "Every course is already offered this term",
                        choose: { course in Task { await store.add(course: course, term: term) } }
                    ),
                    delete: { offering in Task { await store.delete(offering) } },
                    deleteWarning: "The weekly pattern and every session it generated go with it.",
                    selection: $store.selection,
                    notice: store.notice,
                    dismissNotice: { store.notice = nil },
                    appearance: appearance
                )
                .task(id: term) { await store.load(term: term) }
            } else {
                // Not an empty list. A project with no term has nothing an offering could
                // belong to, and a list saying "No offerings yet" beside an Add button that
                // cannot work would be a lie with a button on it.
                EmptyState(
                    symbol: "calendar",
                    title: "No term selected",
                    explanation: "An offering belongs to a term. Choose one in the toolbar.",
                    appearance: appearance
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }
}

@Observable
@MainActor
final class OfferingStore {
    private let connection: EngineConnection

    private(set) var offerings: [Offering] = []
    var selection: Offering.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()
    var localProblems: [String: String] = [:]

    static let editableFields: Set<String> = [
        "per_week", "split_per_attendee", "attendee_ids",
        "duration_slots", "kind", "instructor_ids", "required_feature_ids",
    ]

    /// The catalogue, for labels and for the Add menu.
    private(set) var courses: [Course] = []
    private(set) var groups: [Chooser.Option] = []
    private(set) var instructors: [Chooser.Option] = []
    private(set) var features: [Chooser.Option] = []
    /// How long one slot is, so a duration can be shown in the minutes a person thinks in.
    private(set) var slotMinutes: Int = 60

    /// What the last expansion produced, so the screen can say so rather than going quiet.
    private(set) var lastExpansion: String?

    struct Course: Identifiable, Sendable, Hashable {
        let id: Int
        let code: String
        let name: String
        var label: String { "\(code) — \(name)" }
    }

    struct Offering: Identifiable, Sendable, Hashable {
        let id: Int
        let courseID: Int?
        let courseName: String
        var sessionCount: Int
        var templates: [Template]
    }

    /// One line of the weekly pattern.
    ///
    /// Its **shape** — kind, duration, instructors, features — is fixed at creation and the
    /// engine has no route to change it. That is deliberate (its Decision #54): shape is
    /// copied into each generated session, a session may legitimately have diverged, and
    /// nothing records whether it did — so propagating a shape change would either silently
    /// revert somebody's deliberate edit or leave the pattern and its sessions disagreeing.
    /// Changing shape means deleting the line and adding it again, and the screen says so
    /// rather than offering fields that would not save.
    struct Template: Identifiable, Sendable, Hashable {
        let id: Int
        let kind: String
        let durationSlots: Int
        var perWeek: Int
        var splitPerAttendee: Bool
        var attendeeIDs: Set<Int>
        let attendeeNames: [String]
        let instructorNames: [String]
        let featureNames: [String]
        /// How many sessions this pattern **has** produced — the engine's number, and
        /// zero until somebody expands.
        let generated: Int

        /// How many sessions this pattern **means**, which is what P7's mock shows and is
        /// a different number from `generated` for as long as the two are out of step.
        ///
        /// Computed here rather than read from the engine because the engine does not
        /// publish it: `SessionTemplateRead.session_count` is what exists, stated in its
        /// own docstring. The arithmetic mirrors `domain.SessionTemplate.session_count`,
        /// which is a second copy of one rule (#5) and is accepted deliberately — it is
        /// one multiplication, it is needed *before* any request has been made, and the
        /// probe asserts the two agree after expanding, so drift would be caught rather
        /// than assumed away.
        var wanted: Int {
            splitPerAttendee ? perWeek * max(1, attendeeIDs.count) : perWeek
        }

        /// The pattern and its sessions disagree, so expanding would change something.
        var isStale: Bool { generated != wanted }
    }

    init(connection: EngineConnection) {
        self.connection = connection
    }

    /// Courses that could still be offered this term — the Add menu.
    ///
    /// The engine refuses a duplicate (one offering per course per term), so listing every
    /// course would put choices in the menu whose only outcome is a 409.
    var offerableCourses: [Chooser.Option] {
        let taken = Set(offerings.compactMap(\.courseID))
        return courses.filter { !taken.contains($0.id) }.map { .init(id: $0.id, name: $0.label) }
    }

    func label(for offering: Offering) -> String {
        courses.first { $0.id == offering.courseID }?.label ?? offering.courseName
    }

    func minutes(_ slots: Int) -> Int { slots * slotMinutes }

    func load(term: Int) async {
        do {
            courses = try await connection.run { try await $0.listCourses().ok.body.json }
                .items.map { .init(id: $0.id, code: $0.code, name: $0.name) }
            groups = try await connection.run { try await $0.listGroups().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
            instructors = try await connection.run { try await $0.listInstructors().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
            features = try await connection.run { try await $0.listFeatures().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
            slotMinutes = (try? await TeachingWeek.load(connection, term: term))?.slotMinutes
                ?? slotMinutes

            let page = try await connection.run {
                try await $0.listOfferings(path: .init(term_id: term)).ok.body.json
            }
            offerings = []
            for read in page.items {
                offerings.append(
                    Offering(
                        id: read.id,
                        courseID: read.course?.id,
                        courseName: read.course?.name ?? "Course \(read.id)",
                        sessionCount: read.session_count ?? 0,
                        templates: await templates(of: read.id)
                    )
                )
            }
            if selection == nil { selection = offerings.first?.id }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    private func templates(of offering: Int) async -> [Template] {
        let page = try? await connection.run {
            try await $0.listTemplates(path: .init(offering_id: offering)).ok.body.json
        }
        return (page?.items ?? []).map { read in
            Template(
                id: read.id,
                kind: read.kind.rawValue,
                durationSlots: read.duration_slots,
                perWeek: read.per_week,
                splitPerAttendee: read.split_per_attendee,
                attendeeIDs: Set((read.attendees ?? []).map(\.id)),
                attendeeNames: (read.attendees ?? []).map { $0.name ?? "" },
                instructorNames: (read.instructors ?? []).map { $0.name ?? "" },
                featureNames: (read.required_features ?? []).map { $0.name ?? "" },
                generated: read.session_count ?? 0
            )
        }
    }

    func add(course: Int, term: Int) async {
        forgetLastRefusal()
        do {
            let created = try await connection.run {
                try await $0.createOffering(
                    path: .init(term_id: term),
                    body: .json(.init(course_id: course, term_id: term))
                ).created.body.json
            }
            offerings.append(
                Offering(
                    id: created.id,
                    courseID: created.course?.id,
                    courseName: created.course?.name ?? "",
                    sessionCount: created.session_count ?? 0,
                    templates: []
                )
            )
            selection = created.id
        } catch {
            report(error)
        }
    }

    func delete(_ offering: Offering) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                try await $0.deleteOffering(path: .init(offering_id: offering.id))
            }
            offerings.removeAll { $0.id == offering.id }
            if selection == offering.id { selection = offerings.first?.id }
        } catch {
            report(error)
        }
    }

    // MARK: - The weekly pattern

    func addTemplate(to offering: Int, _ draft: TemplateDraft) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var body = Components.Schemas.SessionTemplateCreate(
                    attendee_ids: Array(draft.attendeeIDs).sorted(),
                    duration_slots: draft.durationSlots,
                    offering_id: offering,
                    per_week: draft.perWeek
                )
                body.kind = .init(rawValue: draft.kind) ?? .lecture
                body.instructor_ids = Array(draft.instructorIDs).sorted()
                body.required_feature_ids = Array(draft.featureIDs).sorted()
                body.split_per_attendee = draft.splitPerAttendee
                return try await $0.createTemplate(
                    path: .init(offering_id: offering), body: .json(body)
                ).created
            }
            await refresh(offering)
        } catch {
            report(error)
        }
    }

    /// Multiplicity only, because that is all the engine accepts (see `Template`).
    func saveTemplate(_ template: Template, in offering: Int) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var changes = Components.Schemas.SessionTemplateUpdate()
                changes.per_week = template.perWeek
                changes.split_per_attendee = template.splitPerAttendee
                changes.attendee_ids = Array(template.attendeeIDs).sorted()
                return try await $0.updateTemplate(
                    path: .init(template_id: template.id), body: .json(changes)
                ).ok
            }
            await refresh(offering)
        } catch {
            report(error)
        }
    }

    func deleteTemplate(_ template: Template, in offering: Int) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                try await $0.deleteTemplate(path: .init(template_id: template.id))
            }
            await refresh(offering)
        } catch {
            // Refused while any generated session is scheduled — the sentence says how many.
            report(error)
        }
    }

    /// Turn the pattern into the sessions the solver will place.
    ///
    /// Explicit rather than automatic on every template edit, because the engine treats it
    /// as a **reconciliation** against sessions that may already be placed and pinned: it
    /// adds what is missing, removes what is no longer wanted, and refuses outright if that
    /// would unschedule somebody's work. A button is the honest interface for an operation
    /// that can be refused.
    func expand(_ offering: Offering) async {
        forgetLastRefusal()
        do {
            let page = try await connection.run {
                try await $0.expandOffering(path: .init(offering_id: offering.id)).ok.body.json
            }
            lastExpansion = page.total == 1
                ? "1 session ready for the solver."
                : "\(page.total) sessions ready for the solver."
            await refresh(offering.id)
        } catch {
            lastExpansion = nil
            report(error)
        }
    }

    /// Re-read one offering from the engine.
    ///
    /// Everything here is derived — `session_count` on the offering, `session_count` on each
    /// template, the resolved attendee and instructor names — so patching the local copy
    /// would be inventing values the engine computes. One request, and it is right.
    private func refresh(_ offering: Int) async {
        guard let read = try? await connection.run({
            try await $0.getOffering(path: .init(offering_id: offering)).ok.body.json
        }) else { return }
        let rows = await templates(of: offering)
        if let index = offerings.firstIndex(where: { $0.id == offering }) {
            offerings[index].sessionCount = read.session_count ?? 0
            offerings[index].templates = rows
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
}

/// A pattern line being composed, before the engine has one.
///
/// A form rather than an add-then-edit, because shape is fixed at creation: a blank line
/// created first and shaped afterwards is exactly what the engine will not accept.
struct TemplateDraft: Equatable {
    var kind = "lecture"
    var durationSlots = 1
    var perWeek = 1
    var splitPerAttendee = false
    var attendeeIDs: Set<Int> = []
    var instructorIDs: Set<Int> = []
    var featureIDs: Set<Int> = []

    static let kinds = ["lecture", "lab", "tutorial", "seminar", "other"]
}
