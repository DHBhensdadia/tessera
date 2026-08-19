import SwiftUI

/// **The only place in the application where a colour literal is allowed to appear.**
///
/// Everything else names a *role* — `.textSecondary`, `.surfaceRaised` — and roles are
/// resolved through `Appearance`. That indirection is what makes a dark scheme, an
/// increased-contrast scheme and a rebrand each a change to this one file rather than a
/// search through every view. A test scans the sources and fails if a literal colour
/// appears anywhere else.
///
/// ## Where these values come from
///
/// Sampled from the reference set rather than chosen, then adjusted where WCAG required
/// it — see R6. Two properties recur across every reference and are the whole character
/// of the palette:
///
/// **Light is cool.** Blue sits above red in every neutral. The earlier palette was warm
/// on the reasoning that a dense grid of text is easier on the eye against cream; that was
/// a real argument and it is not what the references do, so it loses.
///
/// **Dark is exactly neutral.** `#212121`, `#373737`, `#555555` — equal channels, evenly
/// spaced. A three-point blue lean is invisible in a swatch and quite visible across a
/// window.
enum Palette {
    // -- light ------------------------------------------------------------------
    //
    // The reference states its own tokens in its form fields — background `#ECF0F4` — and
    // a panel drawn on it comes out *lighter* than its backdrop, because frosted glass
    // lifts and desaturates rather than tinting. So `raised` is brighter than `base`, and
    // `sunken` — a field, pressed into the surface — is darker than both.
    static let lightBase = Colour(hex: 0xECF0F4)
    static let lightPanel = Colour(hex: 0xF4F7F9)
    static let lightWell = Colour(hex: 0xE1E7EC)

    // Hover and selection **separate from** the plane they sit on, and which direction
    // that is depends on the scheme. A pane is lighter than the window in both, because
    // glass lifts; a selected row is *darker* in light and *lighter* in dark, because what
    // it has to do is stand out from whatever is around it, and there is only one way to
    // go in each.
    //
    // Getting this wrong is visible immediately and invisible to a value test: drawing
    // hover with `panel` made a hovered row read as a near-white card floating on the
    // list — the exact idiom this phase removed, reintroduced by the hover state.
    static let lightHover = Colour(hex: 0xE5EAEF)
    static let lightSelection = Colour(hex: 0xD8E0E7)

    static let lightTextPrimary = Colour(hex: 0x12161C)
    static let lightTextSecondary = Colour(hex: 0x4A5259)
    /// Adjusted from the sampled `#646D75`, which reached only 4.23:1 on `sunken`.
    static let lightTextTertiary = Colour(hex: 0x5E676F)

    static let lightPositive = Colour(hex: 0x146B3A)
    static let lightWarning = Colour(hex: 0x7A4E00)
    static let lightCritical = Colour(hex: 0xA81F16)
    static let lightInfo = Colour(hex: 0x14527E)

    /// Strengthened in 3.1c from the sampled `#DCE2E7`, which reached **1.14:1** on the
    /// window against the dark scheme's 1.28:1 — a hairline noticeably fainter in light
    /// than in dark, and invisible where the sidebar is glass.
    ///
    /// That was tolerable while a rule was decoration. It stopped being tolerable the
    /// moment rules became the only thing grouping anything (#112): a structural device
    /// that works in one of two mandatory schemes is the same failure as the drop shadow
    /// this phase removed, wearing different clothes.
    static let lightBorder = Colour(hex: 0xC9D2DA)
    /// Adjusted from `#8A939B`, which reached only 2.50:1 against `sunken` — a control
    /// outline nobody could locate. WCAG asks 3:1 for a non-text boundary.
    static let lightBorderStrong = Colour(hex: 0x767F87)

    // -- dark -------------------------------------------------------------------
    static let darkBase = Colour(hex: 0x1A1A1A)
    static let darkPanel = Colour(hex: 0x242424)
    static let darkWell = Colour(hex: 0x121212)

    static let darkHover = Colour(hex: 0x232323)
    static let darkSelection = Colour(hex: 0x2E2E2E)

    static let darkTextPrimary = Colour(hex: 0xF2F2F2)
    static let darkTextSecondary = Colour(hex: 0xADADAD)
    /// Adjusted from `#8A8A8A`, which landed exactly on 4.50:1 — passing by nothing.
    static let darkTextTertiary = Colour(hex: 0x909090)

    static let darkPositive = Colour(hex: 0x5FD08A)
    static let darkWarning = Colour(hex: 0xE0A93B)
    static let darkCritical = Colour(hex: 0xFF8A80)
    static let darkInfo = Colour(hex: 0x7FC4F0)

    static let darkBorder = Colour(hex: 0x2E2E2E)
    static let darkBorderStrong = Colour(hex: 0x8A8A8A)

    // -- the accent -------------------------------------------------------------
    //
    // Near-black in light, near-white in dark: the filled control is whatever the
    // background is not. Both light references reach that conclusion — the primary action
    // is `#080917`, not a brand colour — and both dark references answer it with a white
    // pill.
    //
    // The reason is not fashion. A timetable is a dense grid where colour has to *mean*
    // something: a violated constraint, a pinned session, a published scenario. Spending
    // the loudest colour on chrome leaves nothing for meaning, and puts the accent in
    // direct competition with the status roles sitting beside it.
    static let lightAccent = Colour(hex: 0x14181F)
    static let darkAccent = Colour(hex: 0xF2F2F2)

    // Hover lifts toward the surface behind it, pressed sinks away from it — so a filled
    // control reads as rising to meet the pointer and being pushed in. Real colours
    // rather than an opacity on the accent, because a translucent control changes its
    // contrast against whatever happens to be behind it while its label stays put.
    static let lightAccentHover = Colour(hex: 0x232936)
    static let lightAccentPressed = Colour(hex: 0x0A0C10)
    static let darkAccentHover = Colour(hex: 0xFFFFFF)
    static let darkAccentPressed = Colour(hex: 0xD4D4D4)
    static let onLightAccent = Colour(hex: 0xFFFFFF)
    static let onDarkAccent = Colour(hex: 0x17171A)

    // -- focus ------------------------------------------------------------------
    //
    // Blue, and the one place blue survives. macOS uses it for focus and the references
    // agree: in all twelve, blue appears only on the element that is actually selected or
    // focused. Keeping the accent neutral is what leaves that signal legible.
    static let lightFocus = Colour(hex: 0x2F6BD8)
    static let darkFocus = Colour(hex: 0x7EA6FF)
}
