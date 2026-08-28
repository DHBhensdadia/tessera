import Foundation

/// The rule being written, as a sentence, while it is being written.
///
/// D5 calls this the feature, and it is: it is how somebody knows what they are about to
/// create without understanding scopes, target kinds or weights. The alternative is a form
/// of five controls and a Create button that does something you find out about afterwards.
///
/// The template comes from the engine — `ConstraintSpec.summary`, the same string the engine
/// itself fills in when it describes a constraint that already exists. So there is one
/// wording, and a rule reads the same in the form that creates it and in the list underneath.
///
/// Filled in here rather than asked for, because it changes on every keystroke and a round
/// trip per keystroke is absurd. That is safe only because the catalogue promises **bare**
/// placeholders — `{slots}`, never `{slots:>3}` — and a test on the engine enforces it, so
/// this can be a substitution rather than a second implementation of Python's format
/// mini-language.
enum RuleSentence {
    /// The word for "no targets named", supplied by the catalogue per kind.
    ///
    /// Never invented here. "everyone" is right for the five preferences about people and
    /// wrong for the two about courses, which is a mistake the engine made for two phases
    /// and this would repeat if it guessed.
    static func render(
        template: String,
        params: [String: Int],
        targets: [String],
        unnarrowed: String
    ) -> String {
        var sentence = template
        sentence = sentence.replacingOccurrences(
            of: "{targets}",
            with: targets.isEmpty ? unnarrowed : list(targets)
        )
        for (name, value) in params {
            sentence = sentence.replacingOccurrences(of: "{\(name)}", with: String(value))
        }
        return sentence.trimmingCharacters(in: .whitespaces)
    }

    /// Names as somebody would say them: "A", "A and B", "A, B and C".
    ///
    /// The engine's own rendering joins with commas throughout, which is fine for a log and
    /// reads as a list of parts rather than a sentence when it is *in* one.
    static func list(_ names: [String]) -> String {
        switch names.count {
        case 0: ""
        case 1: names[0]
        case 2: "\(names[0]) and \(names[1])"
        default: "\(names.dropLast().joined(separator: ", ")) and \(names[names.count - 1])"
        }
    }

    /// Which placeholders a template still has nothing for.
    ///
    /// Used to keep Create disabled until the sentence is a sentence. A form that lets
    /// somebody submit "Give at most hour(s) in a row" and then explains the refusal is
    /// asking them to read an error to learn what the form wanted.
    static func unfilled(template: String, params: [String: Int]) -> [String] {
        var missing: [String] = []
        var rest = Substring(template)
        while let open = rest.firstIndex(of: "{") {
            guard let close = rest[open...].firstIndex(of: "}") else { break }
            let name = String(rest[rest.index(after: open)..<close])
            if name != "targets", params[name] == nil { missing.append(name) }
            rest = rest[rest.index(after: close)...]
        }
        return missing
    }
}
