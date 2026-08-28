import Testing

@testable import Tessera

/// That the weekly pattern says what it *means* before anybody has run an expansion.
///
/// P7 Act 5 draws `→ generates 3 sessions (A1, A2, A3)` and calls that line the one doing
/// the teaching — it makes the split between a pattern and the sessions it produces visible
/// without documentation. It only teaches if it appears while somebody is still deciding,
/// which is *before* the sessions exist.
///
/// The engine cannot supply the number: `SessionTemplateRead.session_count` is what the
/// pattern **has** generated, stated in the engine's own docstring, and it is zero on a
/// pattern just created. So the screen computes what the pattern means — a second copy of
/// `domain.SessionTemplate.session_count`, accepted deliberately and checked here and in the
/// probe, which asserts the two agree once an expansion has run.
struct WeeklyPatternTests {
    private func template(
        perWeek: Int,
        split: Bool,
        attendees: Set<Int>,
        generated: Int = 0
    ) -> OfferingStore.Template {
        OfferingStore.Template(
            id: 1,
            kind: "lecture",
            durationSlots: 1,
            perWeek: perWeek,
            splitPerAttendee: split,
            attendeeIDs: attendees,
            attendeeNames: [],
            instructorNames: [],
            featureNames: [],
            generated: generated
        )
    }

    /// Three lectures to one cohort is three sessions, however many groups attend.
    @Test func awholeBatchPatternIsItsWeeklyCount() {
        #expect(template(perWeek: 3, split: false, attendees: [1]).wanted == 3)
        #expect(template(perWeek: 3, split: false, attendees: [1, 2, 3]).wanted == 3)
    }

    /// One lab per sub-batch, across three sub-batches, is three sessions. P7's example.
    @Test func aSplitPatternMultipliesByItsAttendees() {
        #expect(template(perWeek: 1, split: true, attendees: [1, 2, 3]).wanted == 3)
        #expect(template(perWeek: 2, split: true, attendees: [1, 2, 3]).wanted == 6)
    }

    /// A split pattern with nobody attending is one the engine refuses outright, so the
    /// arithmetic must not report zero and let a screen draw "→ generates 0 sessions".
    @Test func aSplitPatternWithNoAttendeesDoesNotCollapseToZero() {
        #expect(template(perWeek: 2, split: true, attendees: []).wanted == 2)
    }

    /// Stale means the pattern and its sessions disagree — the normal state after an edit,
    /// and the reason expanding is a button rather than something that happens invisibly.
    @Test func staleIsTheGapBetweenMeaningAndReality() {
        #expect(template(perWeek: 3, split: false, attendees: [1], generated: 0).isStale)
        #expect(template(perWeek: 4, split: false, attendees: [1], generated: 3).isStale)
        #expect(!template(perWeek: 3, split: false, attendees: [1], generated: 3).isStale)
        #expect(!template(perWeek: 1, split: true, attendees: [1, 2], generated: 2).isStale)
    }
}
