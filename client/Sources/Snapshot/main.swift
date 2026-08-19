import AppKit
import DesignSystem
import SwiftUI

/// Renders the design system to PNG files, offscreen, so it can be *looked at* without a
/// display, a window, or anyone being asked to look on your behalf.
///
/// This exists because the phase before it could not close its own loop. `screencapture`
/// needs a Screen Recording grant that a build machine will never have, so a design could
/// be built and never seen by whoever built it. `ImageRenderer` needs nothing: it draws a
/// view into a bitmap in process.
///
/// **What it cannot do.** `glassEffect` renders as *nothing* offscreen — Liquid Glass
/// needs the window server's compositor. A probe drew two of three chips and left the
/// glass one empty. System materials (`.ultraThinMaterial` and friends) do render, and
/// blur a real backdrop. So this covers colour, type, spacing, shape and components; real
/// Liquid Glass is judged in a window, by a person.
///
///     swift run Snapshot [output-directory]
@MainActor
func run() {
    let directory = CommandLine.arguments.count > 1
        ? URL(fileURLWithPath: CommandLine.arguments[1])
        : URL(fileURLWithPath: "build/snapshots")
    try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

    var written = 0
    for scheme in Appearance.Scheme.allCases {
        for sheet in Sheet.allCases {
            let appearance = Appearance(scheme: scheme)
            let name = "\(sheet.rawValue)-\(scheme.rawValue).png"
            guard let data = png(of: sheet.view(appearance), width: sheet.width) else {
                FileHandle.standardError.write(Data("could not render \(name)\n".utf8))
                continue
            }
            try? data.write(to: directory.appending(path: name))
            written += 1
        }
    }
    print("wrote \(written) snapshots to \(directory.path)")
}

@MainActor
private func png(of view: some View, width: CGFloat) -> Data? {
    let renderer = ImageRenderer(content: view.frame(width: width))
    // Retina, because half the point is judging type and hairlines, and both disappear at
    // 1x. Anything above 2 doubles the file for nothing a person can see.
    renderer.scale = 2
    guard let image = renderer.nsImage,
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff) else { return nil }
    return bitmap.representation(using: .png, properties: [:])
}

MainActor.assumeIsolated { run() }
