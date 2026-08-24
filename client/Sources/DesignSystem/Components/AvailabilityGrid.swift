import SwiftUI

/// A teaching week, with the slots somebody cannot be used painted out.
///
/// P7 Act 5: *"Availability is a clickable grid, not a form. Drag across cells to block a
/// range. This same grid component appears for instructor availability — build once, use
/// twice."* So it lives in the design system and knows nothing about rooms, instructors or
/// the engine: it is given a week, a set of blocked slots, and two closures.
///
/// **Slots are week-absolute integers** (#6), which is what the engine stores and what the
/// solver reads: `day × slotsPerDay + slotOfDay`. Breaks are the exception and are
/// *slot-of-day* indices, because a lunch break recurs at the same time every day — storing
/// the week-absolute form would make "move lunch by half an hour" a rewrite of every day.
/// The two coordinate systems meet here and nowhere else.
public struct AvailabilityGrid: View {
    /// The shape of the week. Everything needed to draw it, and nothing about who owns it.
    public struct Week: Hashable, Sendable {
        public let days: Int
        public let slotsPerDay: Int
        public let slotMinutes: Int
        public let dayStartMinute: Int
        /// Slot-of-day indices, per the note above.
        public let breakSlots: Set<Int>

        public init(
            days: Int,
            slotsPerDay: Int,
            slotMinutes: Int,
            dayStartMinute: Int,
            breakSlots: Set<Int> = []
        ) {
            self.days = max(1, days)
            self.slotsPerDay = max(1, slotsPerDay)
            self.slotMinutes = max(1, slotMinutes)
            self.dayStartMinute = dayStartMinute
            self.breakSlots = breakSlots
        }

        public func slot(day: Int, of slotOfDay: Int) -> Int { day * slotsPerDay + slotOfDay }
        public func day(of slot: Int) -> Int { slot / slotsPerDay }
        public func slotOfDay(_ slot: Int) -> Int { slot % slotsPerDay }
        public func isBreak(_ slot: Int) -> Bool { breakSlots.contains(slotOfDay(slot)) }

        /// The clock time a slot-of-day starts at, as a person reads it.
        public func label(forSlotOfDay index: Int) -> String {
            let minute = dayStartMinute + index * slotMinutes
            return String(format: "%02d:%02d", (minute / 60) % 24, minute % 60)
        }
    }

    /// What a drag is doing. Decided by the cell it started on, so both directions are
    /// reachable without a mode switch somebody has to find: begin on a free slot and the
    /// gesture blocks, begin on a blocked one and it frees.
    private enum Painting {
        case blocking(Set<Int>)
        case freeing(Set<Int>)

        var touched: Set<Int> {
            switch self {
            case .blocking(let slots), .freeing(let slots): slots
            }
        }

        func adding(_ slot: Int) -> Painting {
            switch self {
            case .blocking(let slots): .blocking(slots.union([slot]))
            case .freeing(let slots): .freeing(slots.union([slot]))
            }
        }
    }

    private let week: Week
    private let blocked: Set<Int>
    private let block: (Set<Int>) -> Void
    private let free: (Set<Int>) -> Void
    private let isEditable: Bool
    private let appearance: Appearance

    @State private var painting: Painting?

    public init(
        week: Week,
        blocked: Set<Int>,
        editable: Bool = true,
        appearance: Appearance,
        block: @escaping (Set<Int>) -> Void = { _ in },
        free: @escaping (Set<Int>) -> Void = { _ in }
    ) {
        self.week = week
        self.blocked = blocked
        self.isEditable = editable
        self.appearance = appearance
        self.block = block
        self.free = free
    }

    /// Monday first, however many days the grid has. A `TimeGrid` is a count of teaching
    /// days rather than a set of weekdays (#126 records the divergence from P7's mock),
    /// so five days is Monday to Friday and there is no way to express Mon/Wed/Fri.
    private static let dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    private static let timeColumn: CGFloat = 56
    private static let headerRow: CGFloat = 24
    private static let rowHeight: CGFloat = 26

    /// What the grid would look like if the gesture in progress were committed.
    private var shown: Set<Int> {
        switch painting {
        case .blocking(let slots): blocked.union(slots)
        case .freeing(let slots): blocked.subtracting(slots)
        case nil: blocked
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            HStack(spacing: 0) {
                Color.clear.frame(width: Self.timeColumn, height: Self.headerRow)
                ForEach(0..<week.days, id: \.self) { day in
                    SwiftUI.Text(Self.dayNames[min(day, Self.dayNames.count - 1)])
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                        .frame(maxWidth: .infinity, alignment: .center)
                }
            }

            HStack(alignment: .top, spacing: 0) {
                VStack(spacing: 0) {
                    ForEach(0..<week.slotsPerDay, id: \.self) { index in
                        SwiftUI.Text(week.label(forSlotOfDay: index))
                            .font(Typography.caption.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                            .frame(height: Self.rowHeight, alignment: .center)
                            .frame(width: Self.timeColumn, alignment: .trailing)
                            .padding(.trailing, Spacing.snug.points)
                    }
                }
                cells
            }

            if isEditable {
                SwiftUI.Text("Drag across the grid to block time. Drag over blocked time to free it.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
        }
    }

    private var cells: some View {
        GeometryReader { geometry in
            let cellWidth = geometry.size.width / CGFloat(week.days)
            ZStack(alignment: .topLeading) {
                ForEach(0..<(week.days * week.slotsPerDay), id: \.self) { slot in
                    cell(slot)
                        .frame(width: cellWidth, height: Self.rowHeight)
                        .offset(
                            x: CGFloat(week.day(of: slot)) * cellWidth,
                            y: CGFloat(week.slotOfDay(slot)) * Self.rowHeight
                        )
                }
            }
            .contentShape(Rectangle())
            // One gesture over the whole grid rather than one per cell. A cell-level
            // gesture only sees the drag that *started* on it, so a drag across a range
            // would paint the first cell and nothing else — which is the entire feature.
            // Same reasoning as #16 for the timetable editor.
            // A teaching week shown for reference takes no gesture at all. Attaching one
            // that quietly does nothing is worse than attaching none: the cells would
            // highlight under the pointer and then snap back, which reads as a bug.
            .gesture(
                isEditable
                    ? DragGesture(minimumDistance: 0)
                        .onChanged { value in paint(at: value.location, cellWidth: cellWidth) }
                        .onEnded { _ in commit() }
                    : nil
            )
        }
        .frame(height: CGFloat(week.slotsPerDay) * Self.rowHeight)
    }

    @ViewBuilder
    private func cell(_ slot: Int) -> some View {
        let isBreak = week.isBreak(slot)
        Rectangle()
            .fill(fill(slot, isBreak: isBreak))
            .overlay {
                if isBreak {
                    // Hatching rather than a colour: a break is not a third availability
                    // state somebody chose, it is time the grid does not offer at all, and
                    // it must not read as "blocked" in a screenshot or to a colourblind eye.
                    BreakHatching(appearance: appearance)
                }
            }
            .overlay(alignment: .trailing) {
                Rectangle()
                    .fill(appearance.swiftUI(LineRole.border))
                    .frame(width: 1)
            }
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(appearance.swiftUI(LineRole.border))
                    .frame(height: 1)
            }
    }

    private func fill(_ slot: Int, isBreak: Bool) -> Color {
        if isBreak { return appearance.swiftUI(SurfaceRole.well) }
        return shown.contains(slot)
            ? appearance.swiftUI(SurfaceRole.selection)
            : appearance.swiftUI(SurfaceRole.base)
    }

    private func paint(at location: CGPoint, cellWidth: CGFloat) {
        let day = Int(location.x / cellWidth)
        let slotOfDay = Int(location.y / Self.rowHeight)
        guard (0..<week.days).contains(day), (0..<week.slotsPerDay).contains(slotOfDay) else {
            return
        }
        let slot = week.slot(day: day, of: slotOfDay)
        // A break is not paintable, and a drag passing over one must continue rather than
        // stop: dragging a whole morning across lunch is ordinary use.
        guard !week.isBreak(slot) else { return }

        if let painting {
            self.painting = painting.adding(slot)
        } else {
            self.painting = blocked.contains(slot) ? .freeing([slot]) : .blocking([slot])
        }
    }

    private func commit() {
        defer { painting = nil }
        switch painting {
        case .blocking(let slots):
            // Only what actually changes. Re-blocking an already-blocked slot is a no-op
            // for the engine, but sending it means the request no longer says what the
            // gesture meant, which is what a log or a test has to read.
            let wanted = slots.subtracting(blocked)
            if !wanted.isEmpty { block(wanted) }
        case .freeing(let slots):
            let wanted = slots.intersection(blocked)
            if !wanted.isEmpty { free(wanted) }
        case nil:
            break
        }
    }
}

/// Diagonal hatching, for time the grid does not offer.
private struct BreakHatching: View {
    let appearance: Appearance

    var body: some View {
        Canvas { context, size in
            var path = Path()
            var x = -size.height
            while x < size.width {
                path.move(to: CGPoint(x: x, y: size.height))
                path.addLine(to: CGPoint(x: x + size.height, y: 0))
                x += 6
            }
            context.stroke(
                path,
                with: .color(appearance.swiftUI(LineRole.border)),
                lineWidth: 1
            )
        }
        .allowsHitTesting(false)
    }
}
