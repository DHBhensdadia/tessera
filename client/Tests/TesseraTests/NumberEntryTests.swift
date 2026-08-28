import Testing

@testable import Tessera

/// That "no limit" and "that isn't a number" never produce the same request.
///
/// Rooms did not need this: a capacity is required, so `Int(text) ?? 0` sends zero and the
/// engine refuses it by name. An instructor's load limits are `Int?`, where **blank is a
/// value** — and there the same shortcut is silently destructive. `Int("abc")` is `nil`,
/// `nil` is what clearing the limit also sends, so typing nonsense into "at most … per day"
/// would remove the ceiling and the engine would accept it as a deliberate instruction.
struct NumberEntryTests {
    @Test func blankIsAValueAndNonsenseIsNot() {
        #expect(NumberEntry.read("") == .blank)
        #expect(NumberEntry.read("   ") == .blank)
        #expect(NumberEntry.read("4") == .number(4))
        #expect(NumberEntry.read(" 12 ") == .number(12))
        #expect(NumberEntry.read("abc") == .unreadable)
        #expect(NumberEntry.read("3.5") == .unreadable)
        #expect(NumberEntry.read("4x") == .unreadable)
    }

    /// A limit: blank clears it, a number sets it, nonsense yields **no value at all**.
    @Test func anUnreadableLimitYieldsNothingToSend() throws {
        #expect(try NumberEntry.limit("").get() == nil)
        #expect(try NumberEntry.limit("6").get() == 6)

        switch NumberEntry.limit("lots") {
        case .success(let value):
            Issue.record("nonsense produced \(String(describing: value)) — which is what clearing the limit sends")
        case .failure(let complaint):
            #expect(complaint.message.contains("blank"))
        }
    }

    /// A negative limit is *readable*, and refusing it is not this type's job — the engine
    /// already has an opinion about it and a sentence to go with it. A second validator here
    /// is the drift #5 exists to prevent.
    @Test func rangeIsTheEnginesBusiness() throws {
        #expect(try NumberEntry.limit("-3").get() == -3)
        #expect(try NumberEntry.count("0").get() == 0)
    }

    /// A required count has no reading for blank, because there is no value it could mean.
    @Test func blankIsNotACount() throws {
        #expect(NumberEntry.count("") == .failure(NumberEntry.Complaint("Whole numbers only.")))
        #expect(try NumberEntry.count("3").get() == 3)
    }
}
