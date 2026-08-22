import DesignSystem
import SwiftUI

/// A destination that has a name and a place in the sidebar, and no screen yet.
///
/// Not a placeholder in the apologetic sense. 3.4 builds these screens; until then the
/// honest thing to show is the empty state that screen will have anyway, which is a real
/// deliverable of this phase — P5 lists "empty states" among what 3.2 owes.
struct DestinationPlaceholder: View {
    let destination: Destination
    let appearance: Appearance

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection(destination.title, showsRule: false, appearance: appearance) {
                EmptyState(
                    symbol: destination.symbol,
                    title: destination.emptyState.title,
                    explanation: destination.emptyState.explanation,
                    appearance: appearance
                )
                .frame(maxWidth: .infinity)
            }
        }
    }
}

/// What a window shows while its engine is starting.
///
/// It names the step rather than spinning. An engine takes a second or two to come up on a
/// cold launch, and "Starting engine…" answers the question a bare spinner leaves open.
struct StartingUp: View {
    let engine: EngineController
    let appearance: Appearance

    var body: some View {
        VStack(spacing: Spacing.regular.points) {
            ProgressView()
                .controlSize(.small)
            Text(step)
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(appearance.swiftUI(SurfaceRole.base))
    }

    private var step: String {
        if case .starting(let detail) = engine.state { return detail }
        return "Opening…"
    }
}

/// The term this window is looking at.
///
/// In the toolbar rather than the sidebar because switching between Autumn and Spring is
/// the navigation people do minute to minute, while the sidebar navigates *within* one
/// term — Decision #26's distinction, and P7 Act 3's.
struct TermSwitcher: View {
    let summary: ProjectSummary
    let appearance: Appearance

    var body: some View {
        if summary.terms.isEmpty {
            // A project with no terms is mid-creation or broken; either way an empty menu
            // that opens onto nothing is worse than a label that says so.
            Text("No term")
                .font(Typography.caption.font)
                .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
        } else {
            Menu {
                ForEach(summary.terms, id: \.id) { term in
                    Button("\(term.name) \(term.academicYear)") { summary.select(term) }
                }
            } label: {
                Text(summary.selectedTerm.map { "\($0.name) \($0.academicYear)" } ?? "Select a term")
                    .font(Typography.body.font)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
    }
}
