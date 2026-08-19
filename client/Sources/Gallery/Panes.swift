import DesignSystem
import SwiftUI

/// Colour, type and shape — with the measured contrast beside every role, so the numbers
/// the suite asserts are visible rather than only asserted.
struct FoundationsPane: View {
    let appearance: Appearance

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Colour", appearance: appearance) {
                VStack(spacing: 0) {
                    ForEach(roles, id: \.self) { role in
                        HStack {
                            Text("The quick brown fox")
                                .font(Typography.body.font)
                                .foregroundStyle(appearance.swiftUI(role))
                            Spacer()
                            Text(role.rawValue)
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                            Text(ratio(role))
                                .font(Typography.data.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                                .frame(width: 68, alignment: .trailing)
                        }
                        .padding(.vertical, Spacing.snug.points)
                    }
                }
            }
            .id(Entry.colour)

            ContentSection("Type", appearance: appearance) {
                VStack(alignment: .leading, spacing: Spacing.regular.points) {
                    ForEach(Typography.allCases, id: \.self) { style in
                        HStack(alignment: .firstTextBaseline, spacing: Spacing.loose.points) {
                            Text(style == .data ? "09:30  LH-201  60" : "Autumn 2026–27")
                                .font(style.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.primary))
                            Spacer()
                            Text(style.rawValue)
                                .font(Typography.caption.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                        }
                    }
                }
            }
            .id(Entry.type)

            ContentSection("Shape", appearance: appearance) {
                HStack(spacing: Spacing.loose.points) {
                    ForEach(Radius.allCases, id: \.self) { radius in
                        VStack(spacing: Spacing.snug.points) {
                            RoundedRectangle(cornerRadius: radius.points, style: .continuous)
                                .fill(appearance.swiftUI(SurfaceRole.well))
                                .frame(width: 82, height: 48)
                            Text("\(radius.rawValue) \(Int(radius.points))")
                                .font(Typography.data.font)
                                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                        }
                    }
                }
            }
            .id(Entry.shape)
        }
    }

    private var roles: [TextRole] { [.primary, .secondary, .tertiary, .positive, .warning, .critical, .info] }

    private func ratio(_ role: TextRole) -> String {
        let value = appearance.colour(role).contrast(with: appearance.colour(SurfaceRole.base))
        return String(format: "%.2f:1", value)
    }
}

/// Every control, in every state — and, in the first row, controls that are actually live,
/// because a specimen of a hover state proves the colour and not that anything can reach it.
struct ComponentsPane: View {
    let appearance: Appearance
    @State private var roomName = "LH-201"
    @State private var seats = "forty"

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Buttons", appearance: appearance) {
                VStack(alignment: .leading, spacing: Spacing.regular.points) {
                    HStack(spacing: Spacing.snug.points) {
                        ForEach(Emphasis.allCases, id: \.self) { emphasis in
                            ActionButton(emphasis: emphasis, appearance: appearance) {
                                Text("live — point at me")
                            }
                        }
                    }
                    Rule(appearance: appearance)
                        .padding(.vertical, Spacing.snug.points)
                    ForEach(Emphasis.allCases, id: \.self) { emphasis in
                        HStack(spacing: Spacing.snug.points) {
                            ForEach(ControlState.allCases, id: \.self) { state in
                                ActionButton(emphasis: emphasis, state: state, appearance: appearance) {
                                    Text(state.rawValue)
                                }
                            }
                        }
                    }
                }
            }
            .id(Entry.buttons)

            ContentSection("Fields", appearance: appearance) {
                HStack(alignment: .top, spacing: Spacing.loose.points) {
                    Field(label: "Room name", placeholder: "LH-201", value: $roomName, appearance: appearance)
                    Field(
                        label: "Seats",
                        placeholder: "60",
                        value: $seats,
                        problem: "That is not a number of seats.",
                        appearance: appearance
                    )
                }
            }
            .id(Entry.fields)

            ContentSection("Empty states", appearance: appearance) {
                EmptyState(
                    symbol: "rectangle.3.group",
                    title: "No rooms yet",
                    explanation: "Import a spreadsheet, or add the first one by hand.",
                    appearance: appearance
                )
                .frame(maxWidth: .infinity)
            }
            .id(Entry.empty)
        }
    }
}

/// A table, a list, and the badges — the shapes the application spends its time showing.
struct DataPane: View {
    let appearance: Appearance
    @State private var selected: String? = "Computer Lab 1"

    // Numeric columns go last. A right-aligned figure followed by a left-aligned word
    // reads as one field — "60 published" — however much space is between them, because
    // the two are marching toward each other. Visible only once it was rendered.
    private let columns = [
        Column("Room"),
        Column("Location", width: 200),
        Column("Status", width: 120),
        Column("Seats", numeric: true, width: 56),
    ]

    private var rows: [DataRow] {
        [
            ("LH-201", "Block A", "60", "published"),
            ("Computer Lab 1", "Block C", "70", "over capacity"),
            ("Chemistry Lab", "Block B", "40", "draft"),
            ("Seminar Hall", "Block A", "120", "clash"),
        ].map { name, place, seats, status in
            DataRow(id: name, cells: [name, place, status, seats], isSelected: selected == name)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Rooms", appearance: appearance) {
                DataTable(columns: columns, rows: rows, appearance: appearance) { selected = $0 }
                    .padding(.horizontal, -Spacing.regular.points)
            }
            .id(Entry.tables)

            ContentSection("List rows", appearance: appearance) {
                VStack(spacing: 0) {
                    Row("Dr Meera Shah", detail: "Computer Science · 12 hours", value: "12",
                        isSelected: true, appearance: appearance)
                    Row("Prof A. Iyer", detail: "Mathematics · 8 hours", value: "8",
                        appearance: appearance)
                    Row("Dr K. Rao", detail: "Physics · 10 hours", value: "10",
                        appearance: appearance)
                }
            }
            .id(Entry.rows)

            ContentSection("Badges", showsRule: false, appearance: appearance) {
                HStack(spacing: Spacing.snug.points) {
                    ForEach(Badge.Tone.allCases, id: \.self) { tone in
                        Badge(tone.rawValue, tone: tone, appearance: appearance)
                    }
                }
            }
            .id(Entry.badges)
        }
    }
}
