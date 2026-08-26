import DesignSystem
import SwiftUI
import UniformTypeIdentifiers

/// P7 Act 4 puts this at the top of the setup checklist, above "or set up manually":
///
/// ```
/// ┌────────────────────────────────────────────────────────┐
/// │            ↥   Drop a spreadsheet here                 │
/// │           .xlsx, .csv  ·  or  Choose File…             │
/// └────────────────────────────────────────────────────────┘
/// ```
///
/// And says why it comes first: *"Nobody hand-types 200 rooms, and an import that fails
/// opaquely is where most tools lose their users."*
///
/// `.dropDestination` is the right API here. Decision #16 rejected it for the **timetable
/// grid**, because it cannot report which cell a drop landed on — a file dropped anywhere on
/// a pane has no such requirement, and hand-rolling a drag gesture for it would be work in
/// exchange for nothing.
///
/// Both routes end in the same call, so there is one definition of what dropping a
/// spreadsheet means — the same rule the New and Open menu items already follow.
struct DropZone: View {
    let appearance: Appearance
    let take: (ImportStore.Dropped) -> Void

    @State private var isTargeted = false
    @State private var refusal: String?

    /// What the engine can read. Stated here so a drop of something else is refused before
    /// a round trip, and named in the sentence rather than left to be guessed.
    private static let readable: [UTType] = [.commaSeparatedText, .spreadsheet]

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.snug.points) {
            zone
            if let refusal {
                Text(refusal)
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.critical))
            }
        }
    }

    private var zone: some View {
        VStack(spacing: Spacing.snug.points) {
            Image(systemName: "arrow.up.doc")
                .font(.system(size: 22, weight: .light))
                .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            Text("Drop a spreadsheet here")
                .font(Typography.body.font)
                .foregroundStyle(appearance.swiftUI(TextRole.primary))
            HStack(spacing: Spacing.snug.points) {
                Text(".xlsx, .csv")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                Text("·")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
                SwiftUI.Button("Choose File…") { choose() }
                    .buttonStyle(.link)
                    .font(Typography.caption.font)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.section.points)
        .background {
            RoundedRectangle(cornerRadius: Radius.container.points, style: .continuous)
                .fill(appearance.swiftUI(isTargeted ? SurfaceRole.selection : SurfaceRole.well))
        }
        .overlay {
            // Dashed, because a drop target that looks like a panel reads as something to
            // look at rather than something to drop on. It is the one border in the
            // application that is not a hairline, and it says "this is a hole".
            RoundedRectangle(cornerRadius: Radius.container.points, style: .continuous)
                .strokeBorder(
                    appearance.swiftUI(isTargeted ? LineRole.focusRing : LineRole.border),
                    style: StrokeStyle(lineWidth: 1, dash: [4, 4])
                )
        }
        .animation(Motion.control.animation(appearance), value: isTargeted)
        .dropDestination(for: URL.self) { urls, _ in
            guard let url = urls.first else { return false }
            return accept(url)
        } isTargeted: { isTargeted = $0 }
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.title = "Choose a Spreadsheet"
        panel.allowedContentTypes = Self.readable
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        _ = accept(url)
    }

    /// Read it here rather than handing on a URL.
    ///
    /// A dropped file can be anywhere — a Downloads folder, a mounted volume, a Mail
    /// attachment in a temporary directory that is cleaned up behind you. Reading the bytes
    /// at the moment of the drop means the sheet survives everything that happens after,
    /// including the dry run, the mapping correction, and the commit.
    private func accept(_ url: URL) -> Bool {
        do {
            let bytes = try Data(contentsOf: url)
            refusal = nil
            take(ImportStore.Dropped(name: url.lastPathComponent, bytes: Array(bytes)))
            return true
        } catch {
            // Named, because "could not read" without the name is unactionable when three
            // files were dragged from a folder.
            refusal = "\(url.lastPathComponent) could not be read."
            return false
        }
    }
}
