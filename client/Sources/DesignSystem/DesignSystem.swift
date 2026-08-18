/// The visual language, as values rather than as habits.
///
/// This module holds every colour, measurement, duration and material the application is
/// allowed to use, named by the **role** it plays rather than by what it looks like —
/// `Surface.chrome`, not `translucentGrey`. Naming by role is what lets one decision
/// (which material the chrome uses) change in one place for every platform and every
/// accessibility setting.
///
/// It imports nothing from the application and it never will: the package manifest gives
/// it no dependency to do so with. That mirrors what `import-linter` enforces on the
/// Python side, and for the same reason — a layer that can be used on its own is a layer
/// that can be reasoned about on its own.
///
/// Phase 3.1 part 1 establishes the module, its boundary and its place in the build.
/// The tokens arrive in part 2 and the components in part 3, so there is deliberately
/// almost nothing here yet.
public enum DesignSystem {
    /// The version of the visual language, bumped when a token changes meaning rather
    /// than when one is added. Nothing reads it yet; it exists so that when the native
    /// screens in 3.4 start depending on specific roles, "which design system is this
    /// built against" has an answer.
    public static let version = "0.1.0"
}
