import DesignSystem
import SwiftUI

/// The whole interface, for now: whether the engine is up, and why not if it is not.
///
/// Phase 1.5 is a walking skeleton — one thin slice through every layer — so this
/// deliberately shows plumbing rather than a timetable. The window a user will actually
/// meet arrives in Stage 3.
struct StatusView: View {
    let engine: EngineController

    // Read here rather than on the `App`: environment values are resolved per view, and an
    // `App` is not one — the read compiles there and never updates when the system
    // appearance changes.
    @Environment(\.colorScheme) private var colourScheme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    private var appearance: Appearance {
        Appearance(
            scheme: colourScheme == .dark ? .dark : .light,
            reduceTransparency: reduceTransparency
        )
    }

    var body: some View {
        VStack(spacing: Spacing.loose.points) {
            Image(systemName: symbol)
                .font(.system(size: 42, weight: .light))
                .foregroundStyle(tint)
                .symbolEffect(.pulse, isActive: engine.state.isPending)

            Text("Tessera")
                .font(.largeTitle.weight(.semibold))

            Text(summary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            detail

            if case .failed(let error) = engine.state {
                if let log = error.log {
                    ScrollView {
                        Text(log)
                            .font(.system(.caption2, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                    .frame(maxHeight: 120)
                    .padding(Spacing.snug.points)
                    .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: Radius.control.points))
                }
                // The design system's button rather than `.borderedProminent`, which is
                // system blue — in an application whose accent is deliberately a neutral,
                // that one control was the only saturated colour on screen.
                ActionButton(emphasis: .primary, appearance: appearance) {
                    Task { await engine.start() }
                } label: {
                    Text("Restart Engine")
                }
            }
        }
        .padding(Spacing.page.points)
        .frame(width: 420)
        // The window is the glass, rather than a frosted card sitting on an opaque one.
        // That is the difference between using a material and looking like the references.
        .windowGlass(appearance)
    }

    @ViewBuilder
    private var detail: some View {
        if case .running(let running) = engine.state, let health = running.health {
            Grid(
                alignment: .leading,
                horizontalSpacing: Spacing.regular.points,
                verticalSpacing: Spacing.tight.points
            ) {
                row("Project", health.project)
                row("Version", health.version)
                row("Database", health.database)
                row("Port", String(running.port))
            }
            .font(Typography.data.font)
            .padding(Spacing.regular.points)
            .frame(maxWidth: .infinity)
            .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: Radius.control.points))
        }
    }

    private func row(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
    }

    private var summary: String {
        switch engine.state {
        case .idle: "Not started"
        case .starting(let step): step
        case .running: "Engine connected"
        case .failed(let error): error.description
        }
    }

    private var symbol: String {
        switch engine.state {
        case .idle, .starting: "circle.dotted"
        case .running: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
        }
    }

    private var tint: Color {
        switch engine.state {
        case .idle, .starting: .secondary
        case .running: .green
        case .failed: .orange
        }
    }
}
