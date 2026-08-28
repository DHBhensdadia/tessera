import DesignSystem
import SwiftUI

/// P7's mapping table: what each of your columns was taken to mean, and a sample so you can
/// tell which column is which.
///
/// ```
/// Your column        →   Maps to               Sample
/// ───────────────────────────────────────────────────────────
/// Room No            →   [ Name          ⌄ ]   LH-201
/// Floor              →   [ — ignore —    ⌄ ]   2
/// ```
///
/// > **Column mapping is guessed, then editable.** "Seats" → Capacity is inferred; you
/// > correct what it got wrong.
///
/// Every column of the sheet appears, including the ones nothing was made of. A column
/// silently omitted because it matched no field is the one somebody is looking for when they
/// wonder why a field is empty — *"— ignore —"* is an answer, absence is not.
struct ColumnMapping: View {
    let report: ImportStore.Report
    let appearance: Appearance
    let isWorking: Bool
    let remap: (String, String) -> Void

    /// What "map this to nothing" is called. Not an empty menu item: a blank row in a
    /// dropdown reads as a rendering fault.
    private static let ignore = "— ignore —"

    var body: some View {
        ContentSection("Columns", appearance: appearance) {
            // Deliberately not interpolating the current count. The first version said
            // "the difference between \(rowsReady) rows and none", which reads as "the
            // difference between 0 rows and none" in exactly the state where the sentence
            // matters most — a required column unmapped.
            Text("Tessera guessed these from your headings. Correct anything it got wrong: "
                 + "a column pointed at the wrong field can reject every row in the sheet.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.bottom, Spacing.snug.points)

            ForEach(report.columns) { column in
                HStack(alignment: .firstTextBaseline, spacing: Spacing.regular.points) {
                    Text(column.header)
                        .font(Typography.body.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.primary))
                        .frame(width: 150, alignment: .leading)

                    Chooser(
                        label: "",
                        options: options,
                        selection: Binding(
                            get: { index(of: column.mapsTo) },
                            set: { remap(column.header, name(at: $0)) }
                        ),
                        emptyHint: "",
                        appearance: appearance
                    )
                    .frame(width: 180)
                    .disabled(isWorking)

                    // The sample is the point of the row. Monospaced and dimmed: it is
                    // evidence, not a value anybody is being asked to approve.
                    Text(column.sample.isEmpty ? "—" : column.sample)
                        .font(Typography.data.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                }
                .padding(.vertical, Spacing.tight.points)
            }

            if let missing = missingRequired {
                Text(missing)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.critical))
                    .padding(.top, Spacing.snug.points)
            }
        }
    }

    /// `— ignore —` first, then the fields the engine says this kind has. Required ones are
    /// marked, because a mapping that leaves one unfilled produces a report full of rows
    /// that cannot be used, and saying so here is cheaper than saying it two hundred times.
    private var options: [Chooser.Option] {
        [.init(id: 0, name: Self.ignore)]
            + report.fields.enumerated().map { offset, field in
                .init(id: offset + 1, name: field.required ? "\(field.name) (required)" : field.name)
            }
    }

    private func index(of field: String) -> Int? {
        guard let offset = report.fields.firstIndex(where: { $0.name == field }) else { return 0 }
        return offset + 1
    }

    private func name(at id: Int?) -> String {
        guard let id, id > 0, id <= report.fields.count else { return "" }
        return report.fields[id - 1].name
    }

    /// Named rather than counted: "2 required fields are missing" sends somebody hunting
    /// through a dropdown to work out which.
    private var missingRequired: String? {
        let mapped = Set(report.columns.map(\.mapsTo))
        let absent = report.fields.filter { $0.required && !mapped.contains($0.name) }
        guard !absent.isEmpty else { return nil }
        let names = absent.map(\.name).joined(separator: " and ")
        return "No column is mapped to \(names). Every row will be rejected until one is."
    }
}
