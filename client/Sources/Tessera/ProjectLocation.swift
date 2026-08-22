import Foundation

/// Why a project is being opened.
///
/// The difference between the two cases is the difference between creating a project and
/// destroying one, and no amount of inspecting the path can tell them apart — a path that
/// is not there looks identical whether the user has just invented the name in a save
/// panel or whether the file used to be there and has been moved to another disk.
///
/// So it travels with the request. `--must-exist` on the engine is the same distinction
/// on the other side of the process boundary, and `tessera.project.resolve` is where it
/// is finally enforced, because the layout of a package is that module's business.
enum OpenIntent: Sendable {
    /// The user named a location. Anything missing along the way gets made.
    case create
    /// The user pointed at something that is supposed to exist already: Recent Projects,
    /// a double-clicked file, or a window macOS restored after a relaunch.
    case reopen
}

/// A project the application has been asked to open, and the reason.
///
/// A value rather than a bare `URL` so that the intent cannot be dropped on the way to
/// the engine — which is the one mistake in this area that costs somebody their data.
struct ProjectLocation: Hashable, Identifiable, Sendable, Codable {
    let url: URL
    /// Not part of identity. Two requests for the same project are the same window even
    /// if one of them arrived from the Finder and the other from Recent Projects; SwiftUI
    /// uses `Hashable` to decide that, and including the intent would open two.
    let intent: OpenIntent
    /// What a brand-new project should be filled with once its engine is up. Nil for
    /// anything being reopened, and excluded from identity for the same reason as the
    /// intent.
    let setup: ProjectSetup?

    var id: URL { url }

    init(_ url: URL, intent: OpenIntent = .reopen, setup: ProjectSetup? = nil) {
        self.url = url.standardizedFileURL
        self.intent = intent
        self.setup = setup
    }

    static func == (lhs: ProjectLocation, rhs: ProjectLocation) -> Bool { lhs.url == rhs.url }
    func hash(into hasher: inout Hasher) { hasher.combine(url) }

    // MARK: - Identity on the wire
    //
    // `WindowGroup(for:)` identifies a window by the **encoded** value, not by `==`. That
    // is not a detail: with the synthesised `Codable`, the same project arriving from a
    // launch argument and from a Finder double-click encoded differently — different
    // `intent` — so SwiftUI opened a second window and the registry started a second
    // engine on one SQLite file. Exactly the failure the one-engine-per-project rule
    // exists to prevent, and it survived a passing test that asserted `==`, because `==`
    // was never the mechanism.
    //
    // So the encoded form is the URL and nothing else. Two consequences, both wanted:
    // asking for an open project focuses its window, and a window **restored** by macOS
    // decodes as a plain reopen — which is right, because a restored window must never
    // create a project that has gone.

    enum CodingKeys: String, CodingKey { case url }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init(try container.decode(URL.self, forKey: .url))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(url, forKey: .url)
    }

    /// What the window is called: the file name without the extension, which is what the
    /// user typed and what the Finder shows.
    var name: String { url.deletingPathExtension().lastPathComponent }

    /// Where it lives, abbreviated the way the Finder and every macOS Recent list do.
    var folder: String {
        url.deletingLastPathComponent().path(percentEncoded: false)
            .replacingOccurrences(of: NSHomeDirectory(), with: "~")
    }

    /// The extension every project on disk carries. One place, because it appears in the
    /// save panel, the open panel, the type declaration and the file name.
    static let fileExtension = "tessera"
}

extension OpenIntent: Codable {}

/// Why a project could not be opened, in the terms the interface has to answer in.
///
/// Distinct from `EngineError`: these are things the *user* did or that happened to their
/// files, and each one has a different sentence and a different offer attached. An engine
/// that fails to start is a bug; a project that has been moved is a Tuesday.
enum ProjectProblem: Error, Equatable {
    /// It is not there any more. Offer to forget it.
    case missing(ProjectLocation)
    /// Something is there and it is not one of ours.
    case notAProject(ProjectLocation)

    /// Mapped from the engine's exit status rather than from the text of its log.
    ///
    /// Matching on a message is a coupling that survives exactly until somebody improves
    /// the wording, and this is the branch that decides whether the application offers to
    /// delete an entry from the user's Recent Projects.
    init?(exitStatus: Int32, location: ProjectLocation) {
        switch exitStatus {
        case 3: self = .missing(location)
        case 4: self = .notAProject(location)
        default: return nil
        }
    }

    var message: String {
        switch self {
        case .missing(let location):
            "“\(location.name)” is no longer at \(location.folder)."
        case .notAProject(let location):
            "“\(location.name)” is not a Tessera project."
        }
    }

    var explanation: String {
        switch self {
        case .missing:
            "It may have been moved, renamed, or deleted. Nothing has been changed on disk."
        case .notAProject:
            "There is something at that location, but it was not created by Tessera."
        }
    }

    /// Only a project that has genuinely gone is worth offering to forget. A folder that
    /// is not ours might be the user pointing at the wrong thing by accident.
    var offersToForget: Bool {
        if case .missing = self { return true }
        return false
    }
}
