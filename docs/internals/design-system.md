# The design system

Every colour, measurement, duration and material the application is allowed to use, named
by the **role** it plays rather than by what it looks like. `Material.chrome`, not
`translucentGrey`.

It is a separate SwiftPM target with no dependency on the app, which is the same
discipline `import-linter` enforces on the Python side and for the same reason: a layer
that can be used on its own can be reasoned about on its own.

## The one rule the rest of it hangs off

**Structure comes from division and tone. Elevation means "floating above", and nothing
else.**

Groups are separated by a rule and by a step in surface value. A shadow is a claim that
something is above the window — a popover, a sheet, an object being dragged — and it is
spent only where that claim is true.

This replaced the obvious alternative, which the design had for two phases: a rounded
rectangle with a fill and a soft shadow, one per group. That is
`rounded-2xl shadow-lg p-6`, the most recognisable signature of generated interface code,
and Devansh named it on sight. Two things made it indefensible rather than merely
unfashionable:

- **Not one of seventeen reference interfaces does it.** Four show a shadow at all; every
  one is a window, a popover, a sheet, or — on a kanban board where every other card is
  flat — the single card being dragged.
- **Apple's own guidance**: drop shadows separate content in Light Mode and *stop working*
  in Dark Mode, where the platform elevates with lighter material instead. A system whose
  primary grouping device fails in one of two mandatory schemes is not a system. Our own
  dark render proved it — the cards were visible there because they were a lighter grey,
  not because of the shadow.

Enforced rather than remembered: `surface()` cannot draw a shadow, `shadow(` appears
exactly once in the client, and a test names the file and line of any second one.

| | says | draws |
|---|---|---|
| `ContentSection` | *these belong together* | a label, the content, a full-bleed rule beneath |
| `Panel` | *this is a thing* | a hairline, a faint fill, a small radius — no shadow |
| `DataTable` | *this is a table* | a rule under the header, a rule between rows, no container |
| `floating(_:)` | *this is above the window* | the only shadow in the application |

The section owns its horizontal inset so its rule can be full-bleed. That is the whole
difference between dividing a surface and underlining some text.

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

**61 tests, none of which look at a pixel.** Snapshot testing was considered and rejected:
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

### The gallery is built out of the system it documents

It was a specimen sheet first: every component listed in two columns, both schemes side by
side. That version could answer *is this token correct* and could not answer the only
question a design has to answer — *does this look like something a person would use* — for
the same reason a paint chart cannot tell you what a room looks like.

So it is an application now: an icon rail, a sidebar with the quiet grey section labels the
references use, a content pane, and Liquid Glass on the window. Every part of it is drawn
with the tokens, which means the gallery is now also a **witness**: any mistake in the
system is a mistake visible in the tool that shows the system.

The two things it deliberately keeps from the specimen sheet: the measured contrast ratio
printed beside every text role, and the accessibility settings as live toggles rather than
as a legend. Both are there so a claim can be checked while looking at the thing it is
about.

Three flags, because a design tool you cannot get into the state you want to review is a
design tool you do not use:

| | |
|---|---|
| `--light` / `--dark` | forces the scheme, so both are reviewable without changing the appearance of the whole machine |
| `--entry <name>` | opens on one entry — `colour`, `buttons`, `tables`… |
| `--capture` | pins the window to every Space, so a script can launch it and photograph it |

`--capture` exists because of a genuine and confusing failure: launched from a terminal on a
machine using full-screen apps, the window opens on the Space the *process* started on. It
is then open, absent from the on-screen window list, and impossible to photograph — which
looks exactly like an application that failed to start.

### What the gallery caught that the suite did not

Six real defects, all found by looking. The first three came from the specimen sheet:

1. A primary button returned the accent colour for **every** state, so a filled control had
   no hover or press feedback at all.
2. An outlined button used the same surface for normal and hover, so hover was invisible.
3. Labels on a glass specimen were illegible in light mode.

Every existing test passed throughout. The states existed, were enumerated, and were
legible — no test asked whether they *differed*. `everyStateIsVisuallyDistinct` now does,
and the accent family gained real hover and pressed colours rather than an opacity applied
to one.

The next three came from rebuilding it as an application, and each one needed the
application shape to be visible at all:

4. **Outlined controls had no boundary they were required to keep.** Secondary and
   destructive buttons drew `border`, a decorative hairline with no contrast minimum, so
   they read as floating text rather than as something pressable. They draw `borderStrong`
   now, and `ControlBoundaryTests` fails if an outlined control ever picks a role that
   promises nothing.
5. **The sidebar and the content pane were both glass, so the boundary between them
   vanished in light mode** — the hairline was a line drawn between two identical
   materials. The fix was not a darker hairline: the content pane is an opaque surface and
   only the chrome is glass, which is the split every reference makes, and it makes the
   boundary a material change that survives both schemes.
6. **A field that failed validation drew a heavier *neutral* outline**, which reads as
   emphasis — the same emphasis focus uses — rather than as a fault; the red message
   underneath was the only thing carrying the meaning. `LineRole.critical` exists now, and
   because the contrast suite iterates `LineRole.allCases`, adding the case put it under
   test in the same commit.

Defect 5 is the one worth remembering. Two of the three fixes above changed a colour; that
one changed the *structure*, because the defect was not that a token was wrong but that two
different things had been given the same material.

### The failure mode this design system actually has

Three more defects came out of 3.1c, and with the two above they make a pattern worth
naming, because every one of them was found by rendering and none of them could have been
found by a value test.

7. **Hover drew the *pane* colour.** D4 asked for hover to be "a faint fill" and no token
   for one existed, so the first attempt reached for `panel`. In dark a pane is lighter
   than the window, which is what hover wants. In light a pane is near-white — and a
   hovered row came out as a white card floating on the list. The idiom the phase existed
   to remove, walked back in through the hover state, in the same commit that removed it.
8. **A selection drawn with `well` inverted.** A well is *deeper* than the surface in both
   schemes, because a field is deeper in both. A selection has to **separate** from the
   surface, and there is only one direction available in each scheme: darker in light,
   lighter in dark.
9. **The rule was 1.14:1 in light against 1.28:1 in dark** — a hairline noticeably fainter
   in one scheme and absent where the sidebar is glass. Tolerable while a rule was
   decoration; not once rules became the only thing grouping anything.

Together with the vanishing hairline (5) and the neutral error outline (6), that is five
defects of one shape: **a role used somewhere its meaning inverts, or evaporates, between
the two schemes.** It is this design system's characteristic failure, it is invisible to
any test that checks a value rather than a relationship, and the guards written for it now
check *directions and symmetries* rather than numbers:

```swift
#expect((hover.relativeLuminance < base.relativeLuminance) == (scheme == .light))
#expect(max(light, dark) / min(light, dark) <= 1.2)   // a rule, in both schemes
```

The general lesson, which is cheap to state and was expensive to learn: **a token has a
value, but a role has a job, and the job can be scheme-dependent even when the value is
not.**

## Files

| | |
|---|---|
| `client/Sources/DesignSystem/Tokens/Colour.swift` | the value type, and the contrast maths |
| `client/Sources/DesignSystem/Tokens/Palette.swift` | the only colour literals in the project |
| `client/Sources/DesignSystem/Appearance.swift` | roles resolved against scheme and settings |
| `client/Sources/DesignSystem/Surfaces/Material.swift` | glass, material, solid — as a value |
| `client/Sources/DesignSystem/Components/` | buttons, fields, rows, badges, cards, empty states |
| `client/Sources/DesignSystem/Components/Grouping.swift` | `Rule`, `SectionLabel`, `ContentSection`, `Panel` |
| `client/Sources/DesignSystem/Components/DataTable.swift` | a table as a grid of rules |
| `client/Sources/Gallery/` | the system, shown as an application built out of itself |
| `client/Sources/Snapshot/` | the same sheets rendered to PNG offscreen, with no display |

## See also

- [Packaging and the sidecar](packaging.md) — how the client and engine ship together
