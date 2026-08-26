import Testing

@testable import Tessera

/// That the word and the number are the same fact.
///
/// P7 draws these as low / medium / high; the model stores an integer. Both have to mean
/// the same thing, or a weight set in the 2.5 console reads as something else natively —
/// which is the quietest possible way for two interfaces onto one file to disagree.
struct WeightScaleTests {
    @Test(arguments: [
        (1, "low"), (2, "low"), (3, "low"),
        (4, "medium"), (5, "medium"), (6, "medium"),
        (7, "high"), (8, "high"), (9, "high"), (10, "high"),
    ])
    func everyWeightInRangeHasItsWord(weight: Int, word: String) {
        #expect(WeightScale.word(for: weight) == word)
    }

    /// The seeded defaults span 1–8, so every word is reachable from a fresh project.
    ///
    /// A scale whose top bucket only begins above anything the application ever creates
    /// would be a control nobody discovers — and this is the check that would fail if the
    /// defaults or the thresholds moved apart.
    @Test func everyWordIsReachableFromTheSeededDefaults() {
        let seeded = [8, 5, 4, 4, 3, 2, 1]
        let words = Set(seeded.map(WeightScale.word(for:)))
        #expect(words == ["low", "medium", "high"])
    }

    /// The boundaries, stated separately from the table above, because an off-by-one here
    /// is invisible: every value still gets *a* word.
    @Test func theBucketsMeetWhereTheyShould() {
        #expect(WeightScale.word(for: 3) != WeightScale.word(for: 4))
        #expect(WeightScale.word(for: 6) != WeightScale.word(for: 7))
        #expect(WeightScale.word(for: 3) == WeightScale.word(for: 1))
        #expect(WeightScale.word(for: 10) == WeightScale.word(for: 7))
    }

    /// The engine accepts 0, and the scale starts at 1 deliberately: on an enabled soft
    /// constraint 0 means "costs nothing", which is what `enabled` says more clearly.
    /// Leaving 0 on the dial would give the screen two ways to say one thing, and they
    /// would not agree about what the checkbox then shows.
    @Test func theScaleStartsAtOne() {
        #expect(WeightScale.range == 1...10)
    }
}
