import DesignSystem
import EngineClient
import Observation
import SwiftUI

/// Terms — the periods a timetable is built for.
///
/// The project-creation sheet makes the first one, which is why this screen did not exist
/// until the exit test asked for it: running 3.4's parity check found that the console lists
/// terms and teaching weeks and the application had no way to reach either, so a second
/// semester could be created in a browser and nowhere else.
///
/// **A term's academic year and teaching week are fixed at creation.** `TermUpdate` carries
/// name and dates only, because changing the week under a term would invalidate every
/// assignment already made against it (#51 — a `TimeGrid` is immutable, and this is the same
/// reasoning one level up). So Add asks which week, the way Offerings asks which course.
struct TermsScreen: View {
    let appearance: Appearance

    @State private var store: TermStore

    init(connection: EngineConnection, appearance: Appearance) {
        self.appearance = appearance
        _store = State(initialValue: TermStore(connection: connection))
    }

    var body: some View {
        EntityWorkspace(
            title: "Terms",
            items: store.terms,
            label: { "\($0.name) \($0.academicYear)" },
            value: { $0.gridName },
            detail: { term in
                TermDetail(term: term, store: store, appearance: appearance)
            },
            adding: .choosing(
                from: store.grids,
                empty: "No teaching weeks yet — add one first",
                choose: { grid in Task { await store.add(grid: grid) } }
            ),
            delete: { term in Task { await store.delete(term) } },
            deleteWarning: "Everything scheduled in this term goes with it: offerings, sessions and timetables.",
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
final class TermStore {
    private let connection: EngineConnection

    private(set) var terms: [Term] = []
    var selection: Term.ID?
    var notice: String?
    private(set) var fieldErrors = FieldErrors()
    var localProblems: [String: String] = [:]

    static let editableFields: Set<String> = ["name", "starts_on", "ends_on"]

    private(set) var grids: [Chooser.Option] = []
    private var institution: Int?

    struct Term: Identifiable, Sendable, Hashable {
        let id: Int
        var name: String
        let academicYear: String
        /// Dates as the engine writes them, `YYYY-MM-DD`, and empty for "not set".
        var startsOn: String
        var endsOn: String
        let gridName: String?
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
                .items.map { .init(id: $0.id, name: $0.name) }
            terms = try await connection.run { try await $0.listTerms(.init()).ok.body.json }
                .items.map(Self.make)
            if selection == nil { selection = terms.first?.id }
        } catch {
            notice = EngineFailure.unwrap(error).message
        }
    }

    private static func make(_ read: Components.Schemas.TermRead) -> Term {
        Term(
            id: read.id,
            name: read.name,
            academicYear: read.academic_year,
            startsOn: read.starts_on ?? "",
            endsOn: read.ends_on ?? "",
            gridName: read.time_grid?.name
        )
    }

    func add(grid: Int) async {
        forgetLastRefusal()
        guard let institution else {
            notice = "This project has no institution yet, so a term has nothing to belong to."
            return
        }
        let year = Self.currentAcademicYear
        let name = uniqueName()
        do {
            _ = try await connection.run {
                try await $0.createTerm(
                    body: .json(.init(
                        academic_year: year,
                        institution_id: institution,
                        name: name,
                        time_grid_id: grid
                    ))
                ).created
            }
            await load()
            selection = terms.first { $0.name == name && $0.academicYear == year }?.id ?? selection
        } catch {
            report(error)
        }
    }

    func save(_ term: Term) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run {
                var changes = Components.Schemas.TermUpdate()
                changes.name = term.name
                // An empty box means "no date", which is a value the engine accepts; sending
                // the empty string instead would be a 422 about a malformed date.
                changes.starts_on = term.startsOn.isEmpty ? nil : term.startsOn
                changes.ends_on = term.endsOn.isEmpty ? nil : term.endsOn
                return try await $0.updateTerm(path: .init(term_id: term.id), body: .json(changes)).ok
            }
            fieldErrors = FieldErrors()
            notice = nil
            if let index = terms.firstIndex(where: { $0.id == term.id }) { terms[index] = term }
        } catch {
            report(error)
        }
    }

    func delete(_ term: Term) async {
        forgetLastRefusal()
        do {
            _ = try await connection.run { try await $0.deleteTerm(path: .init(term_id: term.id)) }
            terms.removeAll { $0.id == term.id }
            if selection == term.id { selection = terms.first?.id }
        } catch {
            report(error)
        }
    }

    func message(for field: String) -> String? { fieldErrors.message(for: field) }
    func complain(_ message: String?, about field: String) { localProblems[field] = message }
    func problem(for field: String) -> String? { localProblems[field] ?? message(for: field) }

    /// The academic year today falls in, written the way institutions write it.
    ///
    /// The same rule as the creation sheet's: a year running July to June, so August 2026 is
    /// "2026–27" and February 2027 is still "2026–27".
    static var currentAcademicYear: String {
        let now = Calendar.current.dateComponents([.year, .month], from: .now)
        let year = (now.month ?? 1) >= 7 ? (now.year ?? 2026) : (now.year ?? 2026) - 1
        return "\(year)–\(String(format: "%02d", (year + 1) % 100))"
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
        var candidate = "New Term"
        var suffix = 2
        while terms.contains(where: { $0.name == candidate }) {
            candidate = "New Term \(suffix)"
            suffix += 1
        }
        return candidate
    }
}

/// One term.
struct TermDetail: View {
    let term: TermStore.Term
    let store: TermStore
    let appearance: Appearance

    @State private var name = ""
    @State private var startsOn = ""
    @State private var endsOn = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Term", appearance: appearance) {
                Field(
                    label: "Name",
                    placeholder: "Autumn",
                    value: $name,
                    problem: store.problem(for: "name"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Starts on",
                    placeholder: "2026-09-14",
                    value: $startsOn,
                    problem: store.problem(for: "starts_on"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Ends on",
                    placeholder: "2026-12-18",
                    value: $endsOn,
                    problem: store.problem(for: "ends_on"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Text("Dates are optional and written as year-month-day. Press return to save.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }

            ContentSection("Fixed at creation", showsRule: false, appearance: appearance) {
                Row("Academic year", value: term.academicYear, appearance: appearance)
                Row("Teaching week", value: term.gridName ?? "none", appearance: appearance)
                Text("Changing either would invalidate every session already placed in this "
                     + "term, so a different week means a different term.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
        }
        .task(id: term.id) {
            name = term.name
            startsOn = term.startsOn
            endsOn = term.endsOn
        }
    }

    private func commit() {
        var edited = term
        edited.name = name
        edited.startsOn = startsOn
        edited.endsOn = endsOn
        Task { await store.save(edited) }
    }
}
