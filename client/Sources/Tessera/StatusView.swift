import SwiftUI

/// The whole interface, for now: whether the engine is up, and why not if it is not.
///
/// Phase 1.5 is a walking skeleton — one thin slice through every layer — so this
/// deliberately shows plumbing rather than a timetable. The window a user will actually
/// meet arrives in Stage 3.
struct StatusView: View {
    let engine: EngineController

    var body: some View {
        VStack(spacing: 18) {
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
                    .padding(8)
                    .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 8))
                }
                Button("Restart Engine") {
                    Task { await engine.start() }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(28)
        .frame(width: 420)
        .background(.ultraThinMaterial)
    }

    @ViewBuilder
    private var detail: some View {
        if case .running(let running) = engine.state, let health = running.health {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                row("Project", health.project)
                row("Version", health.version)
                row("Database", health.database)
                row("Port", String(running.port))
            }
            .font(.system(.caption, design: .monospaced))
            .padding(10)
            .frame(maxWidth: .infinity)
            .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 8))
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
