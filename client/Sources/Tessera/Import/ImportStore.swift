import EngineClient
import Foundation
import Observation
import OpenAPIRuntime

/// A spreadsheet somebody dropped, and what the engine says about it.
///
/// **The bytes live here for the whole session.** There is no upload-then-reference-later:
/// each call re-reads a file from the request, and the engine's `_REPORTS` holds *reports*
/// rather than files, deliberately — a report is about a file that is not part of the
/// project. So drop, dry run, correct the mapping, dry run again, commit is one file sent
/// several times. For a 200-row sheet that is nothing, and the alternative is a server-side
/// upload cache holding somebody's file for a workflow they may abandon.
///
/// **Nothing is written until `commit()`.** That is the engine's guarantee rather than this
/// screen's care: a dry run runs the same code as a commit — parses, maps, resolves every
/// reference, validates every row, performs every write — and then rolls back. So the report
/// is not an approximation of what would happen, it is what happened, undone.
/// Everything the sheet needs to build its own store.
///
/// The shell hands this over rather than a store, because a store built in the shell is a
/// store built during body evaluation — the fault `StoreOwnershipTests` exists for, and
/// which the guard caught when this was written the other way round. The sheet owns its
/// store in `@State`, as every screen since 3.4 does.
struct ImportRequest: Identifiable, Sendable {
    let id = UUID()
    let connection: EngineConnection
    let term: Int
    let dropped: ImportStore.Dropped
}

@Observable
@MainActor
final class ImportStore: Identifiable {
    /// So the sheet can be presented with `.sheet(item:)`, which is what makes the sheet's
    /// lifetime the store's rather than a separate boolean nobody keeps in step.
    nonisolated let id = UUID()

    private let connection: EngineConnection
    private let term: Int

    /// What was dropped. Held until the sheet is committed or abandoned.
    private(set) var file: Dropped?
    private(set) var report: Report?
    private(set) var isWorking = false
    var notice: String?

    struct Dropped: Sendable {
        let name: String
        let bytes: [UInt8]
    }

    struct Report: Sendable {
        let id: String
        /// rooms, instructors, courses or groups — the four things a project is built out of.
        let kind: String
        let rowsTotal: Int
        let rowsReady: Int
        /// Source column to model field, guessed by the engine and correctable in part 2.
        let mapping: [String: String]
        let problems: [Problem]
        let committed: Bool

        var rowsRejected: Int { max(0, rowsTotal - rowsReady) }
    }

    struct Problem: Identifiable, Sendable {
        let id = UUID()
        let row: Int
        let column: String
        let message: String
        /// A proposed correction, where the engine has one.
        let suggestion: String
    }

    init(connection: EngineConnection, term: Int) {
        self.connection = connection
        self.term = term
    }

    /// Take a file and report on it without writing anything.
    func inspect(_ dropped: Dropped) async {
        file = dropped
        report = nil
        await send(dryRun: true, mapping: nil)
    }

    /// Report again with a corrected column mapping. Part 2's lever.
    func reinspect(mapping: [String: String]) async {
        await send(dryRun: true, mapping: mapping)
    }

    /// Write it.
    func commit() async {
        await send(dryRun: false, mapping: report?.mapping)
    }

    /// Forget the sheet. The file is still on disk; dropping it again is one gesture.
    func discard() {
        file = nil
        report = nil
        notice = nil
    }

    private func send(dryRun: Bool, mapping: [String: String]?) async {
        guard let sheet = file else { return }
        isWorking = true
        notice = nil
        defer { isWorking = false }

        do {
            var parts: [Components.Schemas.Body_importSpreadsheet] = [
                .file(
                    .init(
                        payload: .init(body: HTTPBody(Data(sheet.bytes))),
                        filename: sheet.name
                    )
                )
            ]
            // Sent only when there is one. An empty `mapping` part is not the same as no
            // part: the engine reads it as "override with nothing" and would fail to parse
            // an empty string as JSON.
            if let mapping, let encoded = try? JSONEncoder().encode(mapping),
               let text = String(data: encoded, encoding: .utf8) {
                parts.append(.mapping(.init(payload: .init(body: HTTPBody(text)))))
            }

            let received = try await connection.run {
                try await $0.importSpreadsheet(
                    query: .init(term_id: term, dry_run: dryRun),
                    body: .multipartForm(MultipartBody(parts))
                ).accepted.body.json
            }
            report = Report(
                id: received.import_id,
                kind: received.detected_kind ?? "",
                rowsTotal: received.rows_total ?? 0,
                rowsReady: received.rows_ready ?? 0,
                mapping: received.column_mapping?.additionalProperties ?? [:],
                problems: (received.problems ?? []).map {
                    Problem(
                        row: $0.row,
                        column: $0.column ?? "",
                        message: $0.message,
                        suggestion: $0.suggestion ?? ""
                    )
                },
                committed: received.committed
            )
            // The sheet has been written; the bytes are no longer wanted.
            if received.committed { file = nil }
        } catch {
            // A file that is not a spreadsheet, and one whose columns match nothing, are
            // both 400s carrying the engine's own sentence. Showing that rather than a
            // generic failure is the whole of D6.
            notice = EngineFailure.unwrap(error).message
        }
    }
}
