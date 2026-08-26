import DesignSystem
import SwiftUI

/// What the engine says about the sheet that was dropped, and the decision it asks for.
///
/// Part 1 shows the report and offers the commit. The mapping table (part 2) and the
/// per-row problem list with suggestions (part 3) land in here.
///
/// The sentence about nothing being written is not reassurance, it is the state: a dry run
/// runs the same code as a commit and rolls back, so the numbers on screen are what actually
/// happened once already.
struct ImportSheet: View {
    let request: ImportRequest
    let appearance: Appearance
    let done: () -> Void

    @State private var store: ImportStore

    init(request: ImportRequest, appearance: Appearance, done: @escaping () -> Void) {
        self.request = request
        self.appearance = appearance
        self.done = done
        _store = State(
            initialValue: ImportStore(connection: request.connection, term: request.term)
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let report = store.report {
                summary(report)
                if !report.problems.isEmpty { problems(report) }
                actions(report)
            } else if store.isWorking {
                ContentSection("Reading", showsRule: false, appearance: appearance) {
                    Text("Reading \(store.file?.name ?? "the file")…")
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                }
            } else {
                refusal
            }
        }
        .frame(width: 720)
        .background(appearance.swiftUI(SurfaceRole.panel))
        // The first dry run starts when the sheet appears, not when the file was dropped:
        // the store belongs to this view, and it does not exist until now.
        .task { await store.inspect(request.dropped) }
    }

    private func summary(_ report: ImportStore.Report) -> some View {
        ContentSection(report.committed ? "Imported" : "Ready to import", appearance: appearance) {
            Text("\(store.file?.name ?? "The sheet") looks like \(report.kind).")
                .font(Typography.title.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            Text(report.committed
                 ? "\(report.rowsReady) row(s) written."
                 : "\(report.rowsTotal) row(s) read, \(report.rowsReady) ready"
                   + (report.rowsRejected > 0 ? ", \(report.rowsRejected) that cannot be used." : "."))
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            if !report.committed {
                Text("Nothing has been written yet. Tessera read the whole sheet, resolved "
                     + "every reference and checked every row — then undid it, so these "
                     + "numbers are what will happen rather than an estimate.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func problems(_ report: ImportStore.Report) -> some View {
        ContentSection("\(report.problems.count) row(s) need attention", appearance: appearance) {
            ForEach(report.problems.prefix(12)) { problem in
                HStack(alignment: .firstTextBaseline, spacing: Spacing.regular.points) {
                    Text("Row \(problem.row)")
                        .font(Typography.data.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                        .frame(width: 64, alignment: .leading)
                    VStack(alignment: .leading, spacing: Spacing.hairline.points) {
                        Text(problem.message)
                            .font(Typography.body.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.primary))
                            .fixedSize(horizontal: false, vertical: true)
                        if !problem.suggestion.isEmpty {
                            Text(problem.suggestion)
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                        }
                    }
                }
                .padding(.vertical, Spacing.tight.points)
            }
            if report.problems.count > 12 {
                Text("…and \(report.problems.count - 12) more.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
            Text("These rows are skipped. Correct them in the spreadsheet and drop it "
                 + "again — the rest import either way.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                .padding(.top, Spacing.snug.points)
        }
    }

    private func actions(_ report: ImportStore.Report) -> some View {
        ContentSection("", showsRule: false, appearance: appearance) {
            HStack(spacing: Spacing.regular.points) {
                if report.committed {
                    ActionButton(emphasis: .primary, appearance: appearance, action: done) {
                        Text("Done")
                    }
                } else {
                    ActionButton(appearance: appearance) {
                        store.discard()
                        done()
                    } label: {
                        Text("Cancel")
                    }
                    ActionButton(
                        emphasis: .primary,
                        enabled: report.rowsReady > 0 && !store.isWorking,
                        appearance: appearance
                    ) {
                        Task { await store.commit() }
                    } label: {
                        // The count is on the button because it is the number being agreed
                        // to, and a button that says "Import" alone is a button somebody
                        // presses without knowing what it does.
                        Text("Import \(report.rowsReady) \(report.kind.capitalized)")
                    }
                }
            }
        }
    }

    private var refusal: some View {
        ContentSection("That file cannot be imported", showsRule: false, appearance: appearance) {
            Text(store.notice ?? "The file could not be read.")
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
                .fixedSize(horizontal: false, vertical: true)
            ActionButton(appearance: appearance) {
                store.discard()
                done()
            } label: {
                Text("Close")
            }
        }
    }
}
