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
    let request: ImportRequest?
    let appearance: Appearance
    let done: () -> Void

    @State private var store: ImportStore

    /// A sheet around a store that has already read its file.
    ///
    /// For `--render`, exactly as `ConstraintsScreen` has one: `ImageRenderer` has no run
    /// loop, so `.task` never fires and a sheet that reads its own file would draw the state
    /// where nothing has been read yet.
    init(loaded store: ImportStore, appearance: Appearance) {
        self.request = nil
        self.appearance = appearance
        self.done = {}
        _store = State(initialValue: store)
    }

    init(request: ImportRequest, appearance: Appearance, done: @escaping () -> Void) {
        self.request = request
        self.appearance = appearance
        self.done = done
        _store = State(
            initialValue: ImportStore(connection: request.connection, term: request.term)
        )
    }

    var body: some View {
        content
            .frame(width: 720)
            .background(appearance.swiftUI(SurfaceRole.panel))
            // The first dry run starts when the sheet appears, not when the file was
            // dropped: the store belongs to this view, and it does not exist until now.
            .task { if let request { await store.inspect(request.dropped) } }
    }

    /// The sheet's contents, without the frame the window puts around them.
    ///
    /// Split out for `--render`, the same way `ConstraintsScreen` is: the frame is how a
    /// sheet sits in a window, not part of what it says.
    @ViewBuilder
    var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let report = store.report {
                summary(report)
                if !report.committed {
                    ColumnMapping(
                        report: report,
                        appearance: appearance,
                        isWorking: store.isWorking
                    ) { column, field in
                        Task { await store.remap(column, to: field) }
                    }
                }
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

    /// The rows that cannot be used, and what the engine noticed about them.
    ///
    /// P7 draws per-row fix buttons — *"[ Use projector ] [ Create new ]"* — and there is no
    /// API behind them: the only lever the engine offers is the column mapping, re-sent with
    /// the file. Inventing the buttons here would mean rewriting somebody's spreadsheet in
    /// memory, which is a second answer to what the file says.
    ///
    /// So the honest version: say what is wrong, say what was probably meant where the engine
    /// knows, and say plainly what to do about it. The rest of the sheet imports either way,
    /// which is the thing most worth being clear about — a person who thinks three bad rows
    /// block two hundred good ones will go and fix all two hundred by hand.
    private func problems(_ report: ImportStore.Report) -> some View {
        // Rows, not problems. One row can fail for three reasons at once — a missing name,
        // an unreadable capacity and unknown equipment — and heading the section with the
        // problem count told somebody eight rows were broken when three were. The numbers
        // beside it are row counts, so this one has to be as well.
        ContentSection("\(brokenRows(report)) row(s) cannot be used", appearance: appearance) {
            ForEach(report.problems.prefix(Self.shown)) { problem in
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
                            // The engine sends a name; the sentence is this screen's. It
                            // says what is wrong, we say what to do about it.
                            Text("Did you mean \u{201C}\(problem.suggestion)\u{201D}?")
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                        }
                    }
                }
                .padding(.vertical, Spacing.tight.points)
            }
            if report.problems.count > Self.shown {
                Text("…and \(report.problems.count - Self.shown) more. "
                     + "They are all in the sheet, at the row numbers given.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
            Text(advice(report))
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, Spacing.snug.points)
        }
    }

    private func brokenRows(_ report: ImportStore.Report) -> Int {
        Set(report.problems.map(\.row)).count
    }

    /// Long enough to see the shape of the damage, short enough not to become the screen.
    /// The row numbers are Excel's, so the sheet itself is the better place to read a
    /// hundred of them.
    private static let shown = 12

    private func advice(_ report: ImportStore.Report) -> String {
        report.rowsReady == 0
            ? "No row can be imported as things stand. Check the columns above first — a "
              + "field pointed at the wrong column rejects every row at once."
            : "These rows are skipped; the other \(report.rowsReady) import. Correct them in "
              + "the spreadsheet and drop it again."
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
