import Foundation

/// What a person typed into a numeric field, understood.
///
/// Rooms got away without this: a capacity is required, so `Int(text) ?? 0` sends zero and
/// the engine refuses it with a sentence about capacity. An instructor's three load limits
/// are `Int?`, where **blank means "no limit"** — and there the same shortcut is wrong in a
/// way nothing would report. `Int("abc")` is `nil`, `nil` is a legitimate value, so typing
/// nonsense into "at most … per day" would silently remove the limit and the engine would
/// accept it, because `null` is exactly what a person clearing the field also sends.
///
/// So the three cases are named rather than collapsed. Blank and unreadable are different
/// intentions and must not produce the same request.
///
/// This is a reading of *text*, not a domain rule — the engine never sees what was typed,
/// so there is no second validator here to drift from the first (#5). Anything about what
/// the number is allowed to *be* stays with the engine, which already refuses a negative
/// capacity and a duration longer than a day.
enum NumberEntry {
    enum Reading: Equatable {
        /// The field is empty. For an optional limit this is a value: *no limit*.
        case blank
        case number(Int)
        /// Something was typed and it is not a whole number.
        case unreadable
    }

    static func read(_ text: String) -> Reading {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return .blank }
        guard let value = Int(trimmed) else { return .unreadable }
        return .number(value)
    }

    /// An optional limit: blank clears it, a number sets it, nonsense is refused.
    ///
    /// A `Result` rather than a value and a message beside it. The first version returned
    /// `(value: Int?, problem: String?)` and handed back `nil` for unreadable text — which
    /// is *exactly* the silent clear this type exists to prevent, available to any caller
    /// who forgot to check the second half of the tuple. Now there is no value to send
    /// until the text reads as one.
    static func limit(_ text: String) -> Result<Int?, Complaint> {
        switch read(text) {
        case .blank: .success(nil)
        case .number(let value): .success(value)
        case .unreadable: .failure(Complaint("Whole numbers only — or leave it blank for no limit."))
        }
    }

    /// A required count. Blank is as unreadable as nonsense, because there is no value it
    /// could mean.
    static func count(_ text: String) -> Result<Int, Complaint> {
        switch read(text) {
        case .number(let value): .success(value)
        case .blank, .unreadable: .failure(Complaint("Whole numbers only."))
        }
    }

    /// What to show beside the field. A type rather than a bare `String` so it cannot be
    /// mistaken for a value on the way past.
    struct Complaint: Error, Equatable {
        let message: String
        init(_ message: String) { self.message = message }
    }
}
