import Foundation
import SwiftUI
import Testing

@testable import DesignSystem

/// That grouping stayed a rule and a tone step rather than reverting to a container.
///
/// The whole of 3.1c turns on one distinction: a `Panel` says *this is a thing* and draws
/// an edge; a `ContentSection` says *these belong together* and draws none. Collapsing the
/// second into the first is not a small regression — it is the interface going back to
/// being a page of floating rectangles, which is what Devansh recognised on sight.
///
/// Read from the source, because the mistake is a view modifier rather than a value.
struct GroupingTests {
    /// The text of one type declaration, so a check can be scoped to it rather than to
    /// the file it happens to share with its neighbours.
    static func declaration(of name: String, in path: String) throws -> String {
        let file = NoLiteralsTests.packageRoot.appending(path: path)
        let source = try String(contentsOf: file, encoding: .utf8)
        guard let start = source.range(of: "public struct \(name)") else {
            Issue.record("\(name) is not declared in \(path)")
            return ""
        }
        let rest = source[start.upperBound...]
        // Up to the next top-level declaration, or the end of the file.
        let end = rest.range(of: "\npublic struct ") ?? rest.range(of: "\npublic enum ")
        return String(rest[..<(end?.lowerBound ?? rest.endIndex)])
    }

    static let path = "Sources/DesignSystem/Components/Grouping.swift"

    /// A group has a name and an end. It does not have edges.
    @Test func aContentSectionDrawsNoContainer() throws {
        let body = try Self.declaration(of: "ContentSection", in: Self.path)

        #expect(body.contains("Rule(appearance:"), "a section that does not end is not a section")
        for container in ["strokeBorder", "RoundedRectangle", "Capsule("] {
            #expect(!body.contains(container),
                    "ContentSection draws a \(container) — a group is not an object")
        }
        #expect(!body.contains("SurfaceRole"),
                "ContentSection fills a surface — it should sit on whatever pane it is in")
    }

    /// And the one component that *is* a container still draws its edge.
    ///
    /// Without this, deleting the stroke from `Panel` would leave the check above passing
    /// and the distinction the two types exist to make silently gone.
    @Test func aPanelDrawsItsEdge() throws {
        let body = try Self.declaration(of: "Panel", in: Self.path)
        #expect(body.contains("strokeBorder"), "a Panel with no edge is a ContentSection")
        #expect(body.contains("Radius.container"), "a Panel should use the container radius")
    }

    /// `Card` does not come back.
    ///
    /// Named explicitly rather than left to the checks above, because the way this
    /// regresses is not somebody editing `ContentSection` — it is somebody adding a new
    /// type next to it when a screen wants "just a little separation".
    @Test func nothingIsCalledACardAgain() throws {
        var offences: [String] = []
        for file in NoLiteralsTests.swiftFiles(under: "Sources") {
            let source = try String(contentsOf: file, encoding: .utf8)
            for spelling in ["public struct Card", "struct Card:", "struct Card<"] where source.contains(spelling) {
                offences.append("\(file.lastPathComponent): \(spelling)")
            }
        }
        #expect(offences.isEmpty, "the card is back:\n\(offences.joined(separator: "\n"))")
    }
}

/// That an example value cannot be mistaken for an answer.
///
/// The first render of the three-step project sheet showed "Sardar Patel University" in
/// the institution field at full strength, with Continue disabled and nothing on screen
/// explaining why — because `foregroundStyle` on a `TextField` styles its placeholder too.
struct FieldPlaceholderTests {
    @Test func aPlaceholderIsQuieterThanAnAnswer() {
        #expect(Field.placeholderRole != .primary)
        for scheme in Appearance.Scheme.allCases {
            let appearance = Appearance(scheme: scheme)
            let placeholder = appearance.colour(Field.placeholderRole)
            let typed = appearance.colour(TextRole.primary)
            #expect(
                placeholder.contrast(with: appearance.colour(SurfaceRole.well))
                    < typed.contrast(with: appearance.colour(SurfaceRole.well)),
                "a placeholder is as loud as a real answer in \(scheme.rawValue)"
            )
        }
    }

    /// Quieter, but still readable — it is the only description of what the field wants.
    @Test func andIsStillLegible() {
        for scheme in Appearance.Scheme.allCases {
            let appearance = Appearance(scheme: scheme)
            let ratio = appearance.colour(Field.placeholderRole)
                .contrast(with: appearance.colour(SurfaceRole.well))
            #expect(ratio >= Field.placeholderRole.minimumContrast)
        }
    }
}
