import SwiftUI

/// **The only place in the application where a colour literal is allowed to appear.**
///
/// Everything else names a *role* — `.textSecondary`, `.surfaceRaised` — and roles are
/// resolved through `Appearance`. That indirection is what makes a dark scheme, an
/// increased-contrast scheme and a future rebrand each a change to this one file rather
/// than a search through every view.
///
/// A test scans the sources and fails if a literal colour appears anywhere else, because
/// the rule is only worth having if it is enforced rather than remembered.
///
/// The values are warm rather than neutral — `0xFBFAF8` instead of `0xFFFFFF` for the
/// window — because a timetable is a dense grid of text that people read for an hour at a
/// time, and a pure-white field under that much black text is fatiguing.
enum Palette {
    // -- light ------------------------------------------------------------------
    static let lightBase = Colour(hex: 0xFBFAF8)
    static let lightRaised = Colour(hex: 0xFFFFFF)
    static let lightSunken = Colour(hex: 0xF1EFEA)

    static let lightTextPrimary = Colour(hex: 0x1A1A1C)
    static let lightTextSecondary = Colour(hex: 0x55524C)
    static let lightTextTertiary = Colour(hex: 0x6B6862)

    static let lightAccent = Colour(hex: 0x2F5FD0)
    static let lightPositive = Colour(hex: 0x1E7A46)
    static let lightWarning = Colour(hex: 0x8A5A00)
    static let lightCritical = Colour(hex: 0xB3261E)
    static let lightInfo = Colour(hex: 0x1F5C8C)

    static let lightBorder = Colour(hex: 0xD9D5CD)
    static let lightBorderStrong = Colour(hex: 0x8C887F)

    // -- dark -------------------------------------------------------------------
    static let darkBase = Colour(hex: 0x17171A)
    static let darkRaised = Colour(hex: 0x1F1F23)
    static let darkSunken = Colour(hex: 0x101012)

    static let darkTextPrimary = Colour(hex: 0xF2F1EE)
    static let darkTextSecondary = Colour(hex: 0xB4B1AB)
    static let darkTextTertiary = Colour(hex: 0x918E88)

    static let darkAccent = Colour(hex: 0x7EA6FF)
    static let darkPositive = Colour(hex: 0x5FD08A)
    static let darkWarning = Colour(hex: 0xE0A93B)
    static let darkCritical = Colour(hex: 0xFF8A80)
    static let darkInfo = Colour(hex: 0x7FC4F0)

    static let darkBorder = Colour(hex: 0x3A3A40)
    static let darkBorderStrong = Colour(hex: 0x8A8A93)

    // -- text that sits on the accent -------------------------------------------
    //
    // Not the same in both schemes, and this is the sort of thing a palette gets wrong
    // by assuming. White on the light accent is 5.72:1 and passes; white on the *dark*
    // accent is 2.39:1 and fails badly, because the dark accent is a light blue. Black
    // on it is 8.79:1. So the token is per-scheme, and the contrast test is what would
    // catch anyone "simplifying" it back to white.
    static let onLightAccent = Colour(hex: 0xFFFFFF)
    static let onDarkAccent = Colour(hex: 0x10131A)
}
