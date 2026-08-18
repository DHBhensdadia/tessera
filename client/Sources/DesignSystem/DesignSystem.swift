/// The visual language, as values rather than as habits.
///
/// This module holds every colour, measurement, duration and material the application is
/// allowed to use, named by the **role** it plays rather than by what it looks like —
/// `Material.chrome`, not `translucentGrey`. Naming by role is what lets one decision
/// (which material the chrome uses) change in one place for every platform and every
/// accessibility setting.
///
/// It imports nothing from the application and it never will: the package manifest gives
/// it no dependency to do so with. That mirrors what `import-linter` enforces on the
/// Python side, and for the same reason — a layer that can be used on its own is a layer
/// that can be reasoned about on its own.
///
/// ## Nothing here is named after a SwiftUI type
///
/// Learned the hard way, twice in one sitting. A `Text` role shadowed `SwiftUI.Text`
/// inside the module, so `Text("hello")` started resolving to an enum initialiser and the
/// compiler's explanation was about a missing `rawValue:` label. A `DesignSystem` enum
/// then shadowed the *module* called `DesignSystem`, so `DesignSystem.Button` could not
/// be written at all.
///
/// So: roles are `TextRole`, `SurfaceRole`, `LineRole`, and the button is `ActionButton`.
/// A design system that makes `Text` and `Button` awkward to use is a design system people
/// route around.
public let designSystemVersion = "0.2.0"
