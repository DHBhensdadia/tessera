import SwiftUI

/// One column of a table.
///
/// `isNumeric` is not a formatting hint, it is a typesetting decision: a column of counts,
/// times or durations is set in the tabular `data` face and aligned right, so the digits
/// line up and the eye can compare them by length. Three of the references set every
/// figure this way and it is the clearest single thing separating a table that is read
/// from a table that is merely displayed.
public struct Column: Identifiable, Sendable {
    public let id: String
    public let title: String
    public let isNumeric: Bool
    public let width: CGFloat?

    public init(_ title: String, numeric: Bool = false, width: CGFloat? = nil) {
        self.id = title
        self.title = title
        self.isNumeric = numeric
        self.width = width
    }
}

/// One row of a table: the cells, in column order.
public struct DataRow: Identifiable, Sendable {
    public let id: String
    public let cells: [String]
    public let isSelected: Bool

    public init(id: String, cells: [String], isSelected: Bool = false) {
        self.id = id
        self.cells = cells
        self.isSelected = isSelected
    }
}

/// A table drawn the way the references draw one: **a grid of rules, with no container.**
///
/// The version this replaced was a rounded rectangle with a fill and a shadow, containing
/// rows separated by nothing. That is backwards on both counts. A table is the densest
/// thing in the application and the structure has to come from *inside* it — a header
/// separated by a rule, a rule under every row — rather than from a box drawn around the
/// outside, which tells the eye where the table ends and nothing about how to read it.
///
/// Selection is a **full-bleed band**, not an inset pill. The inset pill is right for a
/// sidebar, where a row is an object in a list; in a table a row is a slice across every
/// column, and a selection that stops short of the edges cuts the columns off.
public struct DataTable: View {
    private let columns: [Column]
    private let rows: [DataRow]
    private let appearance: Appearance
    private let select: ((DataRow.ID) -> Void)?

    @State private var hovered: DataRow.ID?

    public init(
        columns: [Column],
        rows: [DataRow],
        appearance: Appearance,
        select: ((DataRow.ID) -> Void)? = nil
    ) {
        self.columns = columns
        self.rows = rows
        self.appearance = appearance
        self.select = select
    }

    public var body: some View {
        VStack(spacing: 0) {
            header
            Rule(appearance: appearance)
            ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                self.row(row)
                // No rule after the last row: the table ends where the content ends, and
                // a trailing rule would read as an empty row about to be filled.
                if index < rows.count - 1 {
                    Rule(appearance: appearance)
                        .padding(.leading, Spacing.regular.points)
                }
            }
        }
    }

    private var header: some View {
        cells(
            columns.map(\.title),
            font: Typography.caption.font,
            role: .tertiary,
            weight: .regular
        )
        .padding(.vertical, Spacing.snug.points)
    }

    private func row(_ row: DataRow) -> some View {
        cells(
            row.cells,
            font: Typography.body.font,
            role: row.isSelected ? .primary : .secondary,
            weight: row.isSelected ? .semibold : .regular
        )
        .padding(.vertical, Spacing.regular.points)
        .background(background(for: row))
        .contentShape(.rect)
        .onHover { hovered = $0 ? row.id : (hovered == row.id ? nil : hovered) }
        .onTapGesture { select?(row.id) }
        .animation(Motion.control.animation(appearance), value: hovered)
    }

    @ViewBuilder
    private func background(for row: DataRow) -> some View {
        if row.isSelected {
            Rectangle().fill(appearance.swiftUI(SurfaceRole.selection))
        } else if hovered == row.id {
            Rectangle().fill(appearance.swiftUI(SurfaceRole.hover))
        }
    }

    /// One line of the grid. Header and body share it so a column cannot drift out of
    /// alignment with its own heading — which is what happens the moment they are two
    /// separate layouts that merely use the same widths.
    private func cells(
        _ values: [String],
        font: Font,
        role: TextRole,
        weight: Font.Weight
    ) -> some View {
        HStack(spacing: Spacing.regular.points) {
            ForEach(Array(zip(columns, values)), id: \.0.id) { column, value in
                SwiftUI.Text(value)
                    .font(column.isNumeric ? Typography.data.font : font.weight(weight))
                    .foregroundStyle(appearance.swiftUI(role))
                    .lineLimit(1)
                    .frame(
                        width: column.width,
                        alignment: column.isNumeric ? .trailing : .leading
                    )
                    .frame(maxWidth: column.width == nil ? .infinity : nil,
                           alignment: column.isNumeric ? .trailing : .leading)
            }
        }
        .padding(.horizontal, Spacing.regular.points)
    }
}
