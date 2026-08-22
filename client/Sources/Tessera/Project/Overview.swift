import DesignSystem
import SwiftUI

/// P7 Act 4: *"The Overview screen on an empty project is not a blank page. It is a setup
/// checklist, because the honest state of the app is 'you have work to do and I will tell
/// you what it is.'"*
///
/// The checklist is derived from the same counts the sidebar shows, so the two cannot
/// disagree. Constraints are the one row that starts satisfied — every term is seeded with
/// a default set (2.8), so the honest word is "review", not "add".
struct Overview: View {
    let summary: ProjectSummary
    let appearance: Appearance
    let go: (Destination) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Get started", appearance: appearance) {
                Text(headline)
                    .font(Typography.title.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.primary))
                Text("Import a spreadsheet to fill several of these at once, or work "
                     + "through them by hand. Nothing here has to be finished before the "
                     + "next thing is started.")
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
                    .fixedSize(horizontal: false, vertical: true)
            }

            ContentSection("Checklist", appearance: appearance) {
                VStack(spacing: 0) {
                    ForEach(steps, id: \.destination) { step in
                        ChecklistRow(step: step, appearance: appearance) { go(step.destination) }
                    }
                }
            }

            ContentSection("Generate", showsRule: false, appearance: appearance) {
                HStack(spacing: Spacing.regular.points) {
                    ActionButton(emphasis: .primary, enabled: false, appearance: appearance) {
                        Text("Generate Timetable")
                    }
                    Text(readyToGenerate
                         ? "Available once the solver lands in Stage 5."
                         : "Add rooms, instructors and courses first.")
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                }
            }
        }
    }

    private var headline: String {
        guard let term = summary.selectedTerm else { return "Let's set up this project" }
        return "Let's set up \(term.name) \(term.academicYear)"
    }

    private var steps: [ChecklistStep] {
        [
            ChecklistStep(.rooms, summary.count(.rooms), verb: "Add rooms"),
            ChecklistStep(.instructors, summary.count(.instructors), verb: "Add instructors"),
            ChecklistStep(.groups, summary.count(.groups), verb: "Add groups"),
            ChecklistStep(.courses, summary.count(.courses), verb: "Add courses"),
            ChecklistStep(.constraints, summary.count(.constraints), verb: "Review", seeded: true),
        ]
    }

    /// Everything a solve needs a non-zero count of. Constraints are excluded because a
    /// term is seeded with defaults and a project with none is a deliberate choice.
    private var readyToGenerate: Bool {
        [.rooms, .instructors, .courses].allSatisfy { (summary.count($0) ?? 0) > 0 }
    }
}

struct ChecklistStep {
    let destination: Destination
    let count: Int?
    let verb: String
    let seeded: Bool

    init(_ destination: Destination, _ count: Int?, verb: String, seeded: Bool = false) {
        self.destination = destination
        self.count = count
        self.verb = verb
        self.seeded = seeded
    }

    /// Three states, not two. Unknown is what the row shows before the counts arrive, and
    /// it must not look like "none" — a checklist that briefly claims you have no rooms is
    /// a checklist people learn to distrust.
    enum Status { case unknown, empty, done }

    var status: Status {
        guard let count else { return .unknown }
        if seeded { return .done }
        return count > 0 ? .done : .empty
    }

    var detail: String {
        switch status {
        case .unknown: "…"
        case .empty: "Not started"
        case .done: seeded ? "Using defaults" : "\(count ?? 0) added"
        }
    }
}

struct ChecklistRow: View {
    let step: ChecklistStep
    let appearance: Appearance
    let go: () -> Void

    @State private var isHovering = false

    var body: some View {
        HStack(spacing: Spacing.regular.points) {
            Image(systemName: step.status == .done ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 15))
                .foregroundStyle(appearance.swiftUI(step.status == .done ? TextRole.positive : TextRole.tertiary))
            Text(step.destination.title)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            Spacer(minLength: Spacing.snug.points)
            Text(step.detail)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            Text(step.verb)
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.info))
                .frame(width: 110, alignment: .trailing)
        }
        .padding(.vertical, Spacing.regular.points)
        .padding(.horizontal, Spacing.regular.points)
        .background {
            if isHovering {
                RoundedRectangle(cornerRadius: Radius.control.points, style: .continuous)
                    .fill(appearance.swiftUI(SurfaceRole.hover))
            }
        }
        .contentShape(.rect)
        .onHover { isHovering = $0 }
        .onTapGesture(perform: go)
        .animation(Motion.control.animation(appearance), value: isHovering)
    }
}
