import EngineClient
import Foundation

/// Where the engine's complaints go when a form has fields to put them in.
///
/// This is the join 3.3 built one half of. `Field` has carried a `problem:` slot since 3.1
/// — a red outline and a message under the box — and 3.3 made a 422 arrive as a
/// `FieldProblem` whose pointer has already been resolved to a field name. Nothing until
/// now connected the two, so an application that knew exactly which field was wrong showed
/// "validation failed" and left the user to guess.
///
/// The important part is the **unrouted** list. A complaint about a field this form does
/// not have is a bug in the form, and swallowing it makes the bug invisible rather than
/// absent — so it is shown where a message with nowhere better to go is shown, and it
/// stays visible until the next save succeeds.
struct FieldErrors {
    private(set) var byField: [String: String] = [:]
    /// Complaints the form had no field for, and the general message if there was one.
    private(set) var unrouted: [String] = []

    var isEmpty: Bool { byField.isEmpty && unrouted.isEmpty }

    /// What to show under a given field, if anything.
    func message(for field: String) -> String? { byField[field] }

    /// Take a refusal apart against the fields this form actually has.
    ///
    /// `known` is passed rather than inferred because a form knows its own fields and a
    /// dictionary does not — and the difference between "we have nowhere to put this" and
    /// "we quietly dropped it" is the whole point of the type.
    static func from(_ failure: EngineFailure, fields known: Set<String>) -> FieldErrors {
        var errors = FieldErrors()

        for problem in failure.fields {
            let name = problem.fieldName
            // The hint is the engine's suggestion — "use a positive number" — and belongs
            // with the message rather than in a second place nobody looks.
            let text = problem.hint.isEmpty ? problem.message : "\(problem.message) \(problem.hint)"
            if known.contains(name) {
                errors.byField[name] = text
            } else {
                errors.unrouted.append("\(name): \(text)")
            }
        }

        // A refusal with no field complaints at all is the common case — a 409 rule
        // violation carries a sentence and names nothing. That sentence is the message,
        // and it has to appear somewhere or the save looks like it worked.
        if failure.fields.isEmpty {
            errors.unrouted.append(failure.message)
        }
        return errors
    }
}
