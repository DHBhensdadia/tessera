import Testing

@testable import Tessera

/// That the sentence a form shows is the sentence the engine would write.
///
/// The template is the engine's — the same string it fills in when describing a constraint
/// that already exists — so a rule must read identically in the form that creates it and in
/// the list underneath. Filling it in locally is only safe because the catalogue promises
/// bare placeholders, which a test on the engine enforces; these are the other half.
struct RuleSentenceTests {
    @Test func aParameterIsSubstitutedByName() {
        let sentence = RuleSentence.render(
            template: "Give {targets} at most {slots} hour(s) in a row",
            params: ["slots": 3],
            targets: ["Prof. Shah"],
            unnarrowed: "everyone"
        )
        #expect(sentence == "Give Prof. Shah at most 3 hour(s) in a row")
    }

    /// The word for "nobody named" comes from the catalogue, because it differs per kind —
    /// "everyone" is wrong for the two rules about courses, which is a mistake the engine
    /// itself made for two phases.
    @Test func noTargetsUsesTheKindsOwnWord() {
        #expect(
            RuleSentence.render(
                template: "Avoid teaching {targets} twice in one day",
                params: [:], targets: [], unnarrowed: "any course"
            ) == "Avoid teaching any course twice in one day"
        )
    }

    @Test func namesReadAsASentenceRatherThanAList() {
        #expect(RuleSentence.list(["A"]) == "A")
        #expect(RuleSentence.list(["A", "B"]) == "A and B")
        #expect(RuleSentence.list(["A", "B", "C"]) == "A, B and C")
        #expect(RuleSentence.list([]) == "")
    }

    /// Several parameters, and one that is a prefix of another — the case a naive
    /// replace-in-order gets wrong.
    @Test func parametersDoNotOverwriteEachOther() {
        let sentence = RuleSentence.render(
            template: "{days} days and {days_off} off",
            params: ["days": 5, "days_off": 2],
            targets: [], unnarrowed: "everyone"
        )
        #expect(sentence == "5 days and 2 off")
    }

    @Test func itSaysWhichPlaceholdersAreStillEmpty() {
        let template = "Give {targets} at most {slots} hour(s) in a row"
        #expect(RuleSentence.unfilled(template: template, params: [:]) == ["slots"])
        #expect(RuleSentence.unfilled(template: template, params: ["slots": 3]).isEmpty)
    }

    /// `{targets}` is never "unfilled": a global rule with nobody named is a complete rule,
    /// and treating it as missing would disable Create on the commonest thing somebody
    /// writes.
    @Test func targetsAreNotAMissingParameter() {
        #expect(RuleSentence.unfilled(template: "Minimise gaps for {targets}", params: [:]).isEmpty)
    }

    /// Every template the engine actually publishes fills in completely once its parameters
    /// are supplied. A leftover brace on screen is the visible form of the client and the
    /// engine having disagreed about the format.
    @Test func nothingIsLeftOverForAnyRealTemplate() {
        let templates = [
            "Minimise idle gaps in the day for {targets}",
            "Give {targets} at most {slots} hour(s) in a row",
            "Keep {targets} on the same day",
            "Avoid teaching {targets} twice in one day",
        ]
        for template in templates {
            let filled = RuleSentence.render(
                template: template, params: ["slots": 3], targets: ["X"], unnarrowed: "everyone"
            )
            #expect(!filled.contains("{"), "\(template) left a placeholder behind")
            #expect(!filled.contains("}"))
        }
    }
}
