import Foundation
import Testing

@testable import DesignSystem

/// That nothing bypasses the tokens.
///
/// A design system is only worth the indirection if the indirection is actually used. One
/// `Color.blue` in one view is invisible in review, survives forever, and is the reason
/// dark mode ships with a light-blue button on a dark panel.
///
/// So this reads the source. It is a lint expressed as a test, which is the right shape
/// here: it needs no extra tool, it runs in the same gate as everything else, and it
/// fails with the file and line rather than a summary.
struct NoLiteralsTests {
    /// Walk up from this file to the package root, so the test does not depend on where
    /// it was invoked from.
    static var packageRoot: URL {
        var url = URL(fileURLWithPath: #filePath)
        while url.pathComponents.count > 1 {
            url.deleteLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appending(path: "Package.swift").path) {
                return url
            }
        }
        Issue.record("could not find Package.swift above \(#filePath)")
        return url
    }

    /// Every Swift file under a directory — and **never an empty list**.
    ///
    /// A scan that finds no files reports success, so every check built on one would pass
    /// for the worst possible reason. That is not hypothetical: pointing this at a
    /// directory that does not exist left the literal checks green, and only a separate
    /// test noticed, which protected its own call and nothing else. Refusing here covers
    /// every caller at once.
    static func swiftFiles(under directory: String) -> [URL] {
        let root = packageRoot.appending(path: directory)
        let walker = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)
        let found = (walker?.compactMap { $0 as? URL } ?? []).filter { $0.pathExtension == "swift" }
        if found.isEmpty {
            Issue.record("scanned \(root.path) and found no Swift files — the scan is looking in the wrong place")
        }
        return found
    }

    /// Where colour literals are permitted, and nowhere else.
    static let palettePath = "Tokens/Palette.swift"

    @Test func noColourLiteralOutsideThePalette() throws {
        // `Color(.sRGB` is how `Colour.swiftUI` converts, and `Color(hex:` is the
        // palette's own notation. Both are the mechanism rather than a bypass, so the
        // check is scoped by file rather than by spelling.
        let banned = ["Color(red:", "Color(.sRGB", "#colorLiteral", "NSColor(", "Color.blue", "Color.red", "Color.green"]

        var offences: [String] = []
        for file in Self.swiftFiles(under: "Sources") where !file.path.hasSuffix(Self.palettePath) {
            let source = try String(contentsOf: file, encoding: .utf8)
            for (number, line) in source.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
                // The conversion inside `Colour` itself is the one legitimate use.
                if file.lastPathComponent == "Colour.swift", line.contains("Color(.sRGB") { continue }
                for pattern in banned where line.contains(pattern) {
                    offences.append("\(file.lastPathComponent):\(number + 1)  \(line.trimmingCharacters(in: .whitespaces))")
                }
            }
        }

        #expect(
            offences.isEmpty,
            """
            colour literals outside \(Self.palettePath):
            \(offences.joined(separator: "\n"))
            Use a role — Text, Surface or Line — resolved through Appearance.
            """
        )
    }

    /// Raw numbers where a spacing or radius token belongs.
    ///
    /// Scoped to the two modifiers that account for nearly all of them in practice.
    /// A check that tried to ban every numeric literal would flag `0` and `1` constantly
    /// and be switched off within a week, which is worse than a narrower one that stays.
    ///
    /// The patterns are precise about *where* the number is. The first version matched a
    /// `.` immediately after the paren and so flagged every legitimate
    /// `.padding(.horizontal, Spacing.snug.points)` — a check that cries wolf is a check
    /// somebody deletes, which is worse than not having it.
    @Test func noRawNumberWhereATokenExists() throws {
        let patterns = [
            // .padding(12)
            try Regex(#"\.padding\(\s*-?\d"#),
            // .padding(.horizontal, 12)  — a number as the value, not as the edge
            try Regex(#"\.padding\([^)]*,\s*-?\d+(\.\d+)?\s*\)"#),
            // cornerRadius: 8
            try Regex(#"cornerRadius:\s*-?\d"#),
        ]

        var offences: [String] = []
        for file in Self.swiftFiles(under: "Sources") where !file.path.hasSuffix("Tokens/Metrics.swift") {
            let source = try String(contentsOf: file, encoding: .utf8)
            for (number, line) in source.split(separator: "\n", omittingEmptySubsequences: false).enumerated()
            where patterns.contains(where: { line.firstMatch(of: $0) != nil }) {
                offences.append("\(file.lastPathComponent):\(number + 1)  \(line.trimmingCharacters(in: .whitespaces))")
            }
        }

        #expect(
            offences.isEmpty,
            """
            hardcoded measurements:
            \(offences.joined(separator: "\n"))
            Use Spacing or Radius.
            """
        )
    }

    /// The scan is worthless if it is looking in the wrong place, and a scan that finds
    /// no files reports success. This is the guard on the guard.
    @Test func theScanActuallyReadsTheSources() {
        let files = Self.swiftFiles(under: "Sources")
        #expect(files.count >= 8, "expected to scan the whole module, found \(files.count) files")
        #expect(files.contains { $0.lastPathComponent == "Palette.swift" })
        #expect(files.contains { $0.lastPathComponent == "StatusView.swift" }, "the app target must be scanned too")
    }
}

/// That the module does not shadow the framework it is built on.
///
/// Both collisions in this phase were found by the compiler refusing to build the gallery,
/// with error messages that pointed nowhere near the cause — a `Text` role turned
/// `Text("hello")` into an enum initialiser, and a `DesignSystem` enum made
/// `DesignSystem.Button` unwritable. Cheap to assert, and the alternative is finding out
/// again in 3.4 when the real screens are written.
struct NamingTests {
    /// The SwiftUI types a design system is most tempted to name something after.
    static let reserved = [
        "Text", "Button", "Image", "Color", "Font", "Label", "View", "Shape",
        "Divider", "Spacer", "Group", "List", "Section", "Toggle", "Picker",
    ]

    @Test func noPublicTypeShadowsSwiftUI() throws {
        let declaration = try Regex(#"public (?:struct|enum|class|protocol|actor) (\w+)"#)

        var offences: [String] = []
        for file in NoLiteralsTests.swiftFiles(under: "Sources/DesignSystem") {
            let source = try String(contentsOf: file, encoding: .utf8)
            for match in source.matches(of: declaration) {
                guard let captured = match.output[1].substring else { continue }
                let name = String(captured)
                if Self.reserved.contains(name) {
                    offences.append("\(file.lastPathComponent): public \(name)")
                }
            }
        }

        #expect(
            offences.isEmpty,
            """
            these shadow a SwiftUI type and will make the module awkward to import:
            \(offences.joined(separator: "\n"))
            Suffix the role (TextRole) or qualify the component (ActionButton).
            """
        )
    }

    /// The module is called `DesignSystem`, so nothing inside it may be.
    @Test func nothingShadowsTheModuleItself() throws {
        let declaration = try Regex(#"public (?:struct|enum|class|protocol|actor) (\w+)"#)

        for file in NoLiteralsTests.swiftFiles(under: "Sources/DesignSystem") {
            let source = try String(contentsOf: file, encoding: .utf8)
            for match in source.matches(of: declaration)
            where match.output[1].substring.map(String.init) == "DesignSystem" {
                Issue.record("\(file.lastPathComponent) declares a type called DesignSystem, which shadows the module")
            }
        }
    }
}
