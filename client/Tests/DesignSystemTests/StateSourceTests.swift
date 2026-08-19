import SwiftUI
import Testing

@testable import DesignSystem

/// That every state a control can be in is a state a person can actually reach.
struct StateSourceTests {
    /// Precedence, stated as a table. Each line is a decision with a reason recorded on
    /// `StateSource.resolve`, and each one is a thing that looks fine until the case
    /// arises: a disabled control that lights up under the pointer, a focus ring that
    /// vanishes when the mouse moves away.
    @Test func precedenceIsDisabledThenPressedThenFocusedThenHover() {
        let live = StateSource.live
        #expect(live.resolve(hovering: true, pressing: true, focused: true, enabled: false) == .disabled)
        #expect(live.resolve(hovering: true, pressing: true, focused: true, enabled: true) == .pressed)
        #expect(live.resolve(hovering: true, pressing: false, focused: true, enabled: true) == .focused)
        #expect(live.resolve(hovering: true, pressing: false, focused: false, enabled: true) == .hover)
        #expect(live.resolve(hovering: false, pressing: false, focused: false, enabled: true) == .normal)
    }

    /// Pinning overrides everything, including disabled — a specimen sheet has to be able
    /// to draw a hovered control that nothing is hovering.
    @Test func pinningWins() {
        for state in ControlState.allCases {
            let pinned = StateSource.pinned(state)
            #expect(pinned.resolve(hovering: false, pressing: false, focused: false, enabled: true) == state)
        }
    }

    /// The default is live. This is the whole defect #114 recorded: before 3.1c the only
    /// way to get a state was to pass one, so every control in the application was frozen
    /// at `.normal` and the hover colours were unreachable.
    @Test func controlsAreLiveUnlessDeliberatelyPinned() {
        let appearance = Appearance()
        #expect(ActionButton(appearance: appearance) { SwiftUI.Text("x") }.source == .live)
        #expect(Row("x", appearance: appearance).source == .live)
        #expect(Field(label: "x", value: .constant(""), appearance: appearance).source == .live)

        #expect(
            ActionButton(state: .hover, appearance: appearance) { SwiftUI.Text("x") }.source
                == .pinned(.hover)
        )
    }

    /// And that the live path is actually wired to the pointer.
    ///
    /// The value test above proves the *default* is `.live`. It cannot prove anything
    /// observes the pointer — which is exactly the shape of the original defect, where
    /// `ControlState` existed, was enumerated, was proved distinct, and was never fed by
    /// anything. So this reads the source for the one API that can feed it.
    @Test func everyInteractiveComponentInstallsAHoverSource() throws {
        for component in ["Control.swift", "Panels.swift"] {
            let file = NoLiteralsTests.packageRoot
                .appending(path: "Sources/DesignSystem/Components/\(component)")
            let source = try String(contentsOf: file, encoding: .utf8)
            // Either spelling counts. The first version of this demanded `.onHover`
            // exactly, and rejected `.onContinuousHover` — which is a perfectly good
            // hover source, so the guard was enforcing a spelling while claiming to
            // enforce a behaviour. Found by breaking it with the wrong thing.
            let sources = [".onHover", ".onContinuousHover"]
            #expect(sources.contains(where: source.contains),
                    "\(component) draws hover states that nothing can reach")
        }
    }
}
