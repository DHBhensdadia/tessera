import DesignSystem
import SwiftUI

/// P7 Act 2, in three steps.
///
/// Three rather than one form because the middle step is the most consequential screen in
/// the application — changing a time grid later invalidates every assignment — and burying
/// it in a long form is how it gets skipped. The steps are also the honest shape of the
/// decision: who you are, how your week is divided, and which term you are starting with.
///
/// Nothing exists on disk until the last button. Cancel at any point and no directory, no
/// database and no engine were ever created.
struct NewProjectSheet: View {
    @Binding var setup: ProjectSetup
    let appearance: Appearance
    let cancel: () -> Void
    let confirm: () -> Void

    @State private var step = 0

    private let titles = ["Identity", "The teaching week", "First term"]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Rule(appearance: appearance)

            Group {
                switch step {
                case 0: identity
                case 1: TimeGridStep(grid: $setup.grid, appearance: appearance)
                default: firstTerm
                }
            }
            .padding(Spacing.page.points)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            Rule(appearance: appearance)
            footer
        }
        .frame(width: 620, height: 560)
        .background(appearance.swiftUI(SurfaceRole.base))
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(titles[step])
                .font(Typography.heading.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            Spacer()
            Text("Step \(step + 1) of 3")
                .font(Typography.data.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        }
        .padding(Spacing.page.points)
    }

    private var footer: some View {
        HStack(spacing: Spacing.snug.points) {
            ActionButton(appearance: appearance, action: cancel) { Text("Cancel") }
            Spacer()
            if step > 0 {
                ActionButton(appearance: appearance) { step -= 1 } label: { Text("Back") }
            }
            if step < 2 {
                ActionButton(emphasis: .primary, enabled: canAdvance, appearance: appearance) {
                    step += 1
                } label: {
                    Text("Continue")
                }
            } else {
                ActionButton(emphasis: .primary, enabled: canAdvance, appearance: appearance, action: confirm) {
                    Text("Choose Location…")
                }
            }
        }
        .padding(Spacing.page.points)
    }

    /// Nothing advances on an empty answer. The alternative is a project called "" whose
    /// institution is "", which the engine would accept and nobody could use.
    private var canAdvance: Bool {
        switch step {
        case 0: !setup.institution.trimmingCharacters(in: .whitespaces).isEmpty
        case 1: setup.grid.usableSlotsPerDay > 0
        default: !setup.termName.trimmingCharacters(in: .whitespaces).isEmpty
            && !setup.academicYear.trimmingCharacters(in: .whitespaces).isEmpty
        }
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: Spacing.loose.points) {
            Field(
                label: "Institution",
                placeholder: "Sardar Patel University",
                value: $setup.institution,
                appearance: appearance
            )
            Text("The name that appears on printed timetables. You can change it later.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        }
    }

    private var firstTerm: some View {
        VStack(alignment: .leading, spacing: Spacing.loose.points) {
            HStack(alignment: .top, spacing: Spacing.loose.points) {
                Field(label: "Academic year", value: $setup.academicYear, appearance: appearance)
                Field(label: "Term", placeholder: "Autumn", value: $setup.termName, appearance: appearance)
            }
            Text("A term is one repeating week of teaching. You can add more later, and "
                 + "duplicate this one to carry its rules forward.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// The grid step, with the strip that turns an abstract choice into a visible week.
struct TimeGridStep: View {
    @Binding var grid: TimeGridSetup
    let appearance: Appearance

    private let dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.section.points) {
            days
            hours
            preview
        }
    }

    /// A count, not a set of weekdays.
    ///
    /// The model addresses a week by integer slot index over `days` consecutive days, so
    /// "Monday, Wednesday and Friday" has no representation. P7's mock shows a checkbox per
    /// day; drawing that here would let somebody build a grid that means something other
    /// than what they ticked.
    private var days: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            SectionLabel("Teaching days", appearance: appearance)
            HStack(spacing: Spacing.tight.points) {
                ForEach(Array(dayNames.enumerated()), id: \.offset) { index, name in
                    let included = index < grid.days
                    Text(name)
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(included ? TextRole.onAccent : TextRole.tertiary))
                        .frame(width: 46, height: 28)
                        .background {
                            RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                                .fill(appearance.swiftUI(included ? SurfaceRole.accent : SurfaceRole.well))
                        }
                        .contentShape(.rect)
                        .onTapGesture { grid.days = index + 1 }
                }
            }
            Text("Counted from Monday. A week of \(grid.days) consecutive teaching days.")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        }
    }

    private var hours: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            SectionLabel("The day", appearance: appearance)
            HStack(spacing: Spacing.section.points) {
                stepper("Starts", value: $grid.startMinute, step: 30, range: 0...(12 * 60))
                stepper("Ends", value: $grid.endMinute, step: 30, range: (grid.startMinute + 60)...(24 * 60))
                VStack(alignment: .leading, spacing: Spacing.tight.points) {
                    Text("Slot length")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    Picker("", selection: $grid.slotMinutes) {
                        ForEach([15, 30, 60], id: \.self) { Text("\($0) min").tag($0) }
                    }
                    .labelsHidden()
                    .pickerStyle(.segmented)
                    .frame(width: 210)
                }
            }
        }
    }

    private func stepper(_ label: String, value: Binding<Int>, step: Int, range: ClosedRange<Int>) -> some View {
        VStack(alignment: .leading, spacing: Spacing.tight.points) {
            Text(label)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            Stepper(value: value, in: range, step: step) {
                Text(value.wrappedValue.asClockTime)
                    .font(Typography.data.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
            }
            .frame(width: 130)
        }
    }

    /// The strip P7 asks for: the abstract choice of "30 minutes" becomes a visible week,
    /// and the slot count is stated because that number is what the solver works with.
    private var preview: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            SectionLabel("Preview", appearance: appearance)
            VStack(alignment: .leading, spacing: Spacing.tight.points) {
                ForEach(0..<grid.days, id: \.self) { day in
                    HStack(spacing: Spacing.tight.points) {
                        Text(dayNames[min(day, 6)])
                            .font(Typography.data.font)
                            .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                            .frame(width: 34, alignment: .leading)
                        HStack(spacing: 1) {
                            ForEach(0..<grid.slotsPerDay, id: \.self) { slot in
                                Rectangle()
                                    .fill(appearance.swiftUI(
                                        grid.breakSlots.contains(slot) ? SurfaceRole.well : SurfaceRole.accent
                                    ))
                                    .frame(height: 12)
                            }
                        }
                    }
                }
            }
            Text("\(grid.usableSlotsPerDay) usable slots per day · \(grid.usableSlotsPerWeek) per week")
                .font(Typography.data.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
        }
    }
}
