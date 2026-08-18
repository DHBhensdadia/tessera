# The design system

Every colour, measurement, duration and material the application is allowed to use, named
by the **role** it plays rather than by what it looks like. `Material.chrome`, not
`translucentGrey`.

It is a separate SwiftPM target with no dependency on the app, which is the same
discipline `import-linter` enforces on the Python side and for the same reason: a layer
that can be used on its own can be reasoned about on its own.

## Why colour is a value type and not `Color`

SwiftUI's `Color` is opaque. Its components cannot be read back reliably without going
through AppKit and a colour-space conversion that varies by display — so *"is this text
legible on that background"* could not be asserted in a test.

Legibility is the one property of a palette worth proving rather than assuming, so a token
is sRGB components in `0...1`, converted to `Color` only at the moment of drawing. WCAG
relative luminance and contrast are then plain arithmetic that runs anywhere.

```swift
public func contrast(with other: Colour) -> Double {
    let a = relativeLuminance, b = other.relativeLuminance
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)
}
```

The formula is checked against WCAG's own reference values — black on white is 21:1,
`#767676` on white is the 4.54:1 boundary case from their examples — so a mistake in the
maths surfaces as a wrong answer rather than as a palette that quietly passes.

**It paid immediately.** White on the light accent is 5.72:1; white on the *dark* accent is
2.39:1, because that accent is a pale blue. A palette written by eye carries one `onAccent`
value. This one carries two, because the arithmetic said so before anything was drawn.

## Roles, and one file of literals

`Palette.swift` is the only file permitted a colour literal, and a test scans the sources
to keep it that way. Everything else names a role and resolves it through `Appearance`:

```
TextRole      primary secondary tertiary onAccent positive warning critical info
SurfaceRole   base raised sunken accent accentHover accentPressed
LineRole      border borderStrong focusRing
```

`Appearance` carries the colour scheme, the three accessibility settings, and whether the
platform can draw Liquid Glass. **Passing it explicitly rather than reading the environment
inside each component is what makes the system testable without rendering anything** — and
what lets the gallery show all sixteen combinations side by side on one screen.

### The accessibility settings are branches, not decoration

| Setting | What changes | Why it is not cosmetic |
|---|---|---|
| **Reduce Transparency** | every material becomes a flat colour | translucency makes text unreadable for some people, and macOS turns it on itself in Low Power Mode |
| **Increase Contrast** | muted text collapses to the primary colour; hairlines become real lines | the setting exists for people who cannot read low-contrast text — a marginally less grey grey helps nobody |
| **Reduce Motion** | durations collapse to a 10 ms cross-fade | vestibular disorders. Not to zero: a control that changes with no transition reads as a glitch |

A test asserts each one changes the resolved value, and that Increase Contrast never
*reduces* a ratio — which is easy to break by hand-picking a "stronger" colour with less
luminance separation.

## Materials: one token, three implementations

Apple's guidance for the 26 releases is explicit that Liquid Glass belongs to the
**functional** layer — controls, navigation, transient surfaces — and never to content.
That is expressed here as *which roles exist*, which is a better enforcement than a code
review because `.content` has no path to glass.

```swift
public enum Material { case chrome, content, overlay }   // content is never glass
```

The decision is a pure function returning a value, so it can be asserted with no window:

```swift
public func fill(for material: Material) -> Fill    // .solid / .systemMaterial / .liquidGlass
```

Reduce Transparency outranks the platform. Getting that the other way round would mean the
newest OS ignored the setting, which is the worst possible combination.

**Platform support is part of the `Appearance` value**, not a `#available` inside the
function. Without that, the macOS 14–15 branch would be unreachable from a suite running on
macOS 26 — which is to say untested on the only versions where it is used.

## Text never sits directly on glass

Glass has no fixed luminance: it refracts whatever is behind the window. **No contrast
ratio exists for text on it**, which is why the promised pairings cover only opaque roles.

This was not reasoned out in advance — the gallery showed it. Labels drawn straight onto a
glass specimen were washed out in light mode, and no test could have said so because no
test had anything to measure. The rule that follows is structural: prose belongs on
`.content`, which is always solid. Chrome and overlay carry controls, not paragraphs.

## Nothing is named after a SwiftUI type

Learned twice in one sitting, both times found by the compiler refusing to build the
gallery with an error that pointed nowhere near the cause.

- A `Text` role shadowed `SwiftUI.Text` **inside the module**, so `Text("hello")` became an
  enum initialiser and the error was about a missing `rawValue:` label.
- A `DesignSystem` enum shadowed the *module* called `DesignSystem`, so
  `DesignSystem.Button` could not be written at all.

Hence `TextRole`, `SurfaceRole`, `LineRole`, and `ActionButton`. A test asserts no public
type is named after one of the fourteen SwiftUI types a design system is most tempted to
reuse.

## What the tests prove, and what they do not

**34 tests, none of which look at a pixel.** Snapshot testing was considered and rejected:
the exit test asks for correct rendering on macOS 14 *and* 26, two versions that are
supposed to differ, so a pixel comparison would fail on exactly the thing the design
intends. It goes to the backlog for when the layout settles.

| Proved | Not proved |
|---|---|
| Every role resolves in both schemes | That the palette is attractive |
| Every promised pairing meets WCAG AA | That the type scale feels right |
| No view bypasses the tokens | That the spacing rhythm reads well |
| Each accessibility setting changes the render | That a person enjoys using it |
| Every control state is visually distinct | |

**The gallery is where the second column is judged**, and it is judged by a person. That is
stated rather than dressed up as a test.

```bash
swift run --package-path client -c release Gallery
```

It shows both schemes side by side — a design is reviewed by comparison, and flipping
between them from memory is how a dark mode ships with one panel a shade wrong — with the
accessibility settings and the Liquid Glass switch as live toggles, and the measured
contrast ratio printed beside every text role.

### What the gallery caught that the suite did not

Three real defects, all found by looking:

1. A primary button returned the accent colour for **every** state, so a filled control had
   no hover or press feedback at all.
2. An outlined button used the same surface for normal and hover, so hover was invisible.
3. Labels on a glass specimen were illegible in light mode.

Every existing test passed throughout. The states existed, were enumerated, and were
legible — no test asked whether they *differed*. `everyStateIsVisuallyDistinct` now does,
and the accent family gained real hover and pressed colours rather than an opacity applied
to one.

## Files

| | |
|---|---|
| `client/Sources/DesignSystem/Tokens/Colour.swift` | the value type, and the contrast maths |
| `client/Sources/DesignSystem/Tokens/Palette.swift` | the only colour literals in the project |
| `client/Sources/DesignSystem/Appearance.swift` | roles resolved against scheme and settings |
| `client/Sources/DesignSystem/Surfaces/Material.swift` | glass, material, solid — as a value |
| `client/Sources/DesignSystem/Components/` | buttons, fields, rows, badges, cards, empty states |
| `client/Sources/Gallery/` | every component, every state, both schemes |

## See also

- [Packaging and the sidecar](packaging.md) — how the client and engine ship together
