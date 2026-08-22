import AppKit
import Observation

/// The projects this person has opened, most recent first.
///
/// Two lists rather than one, and both are needed. `NSDocumentController` populates the
/// system's *Open Recent* menu and works without `NSDocument`, so the menu bar behaves the
/// way every other Mac application does. Our own list backs the welcome window, which shows
/// a name, a folder and a time — none of which the system menu can express.
///
/// Plain paths, no security-scoped bookmarks: the bundle declares no App Sandbox, so file
/// access is unrestricted. That answer changes entirely if 7.3 ever adds the sandbox, which
/// is why it is written down rather than assumed.
@Observable
@MainActor
final class RecentProjects {
    /// How many the welcome window shows. Enough to cover a term's worth of switching
    /// between two or three projects, short enough that the list stays scannable.
    static let limit = 8

    private static let key = "RecentProjects"

    private(set) var entries: [Entry] = []
    private let defaults: UserDefaults

    struct Entry: Codable, Identifiable, Hashable, Sendable {
        let url: URL
        let openedAt: Date

        var id: URL { url }
        var location: ProjectLocation { ProjectLocation(url, intent: .reopen) }
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        entries = Self.load(from: defaults)
    }

    func note(_ location: ProjectLocation) {
        entries.removeAll { $0.url == location.url }
        entries.insert(Entry(url: location.url, openedAt: .now), at: 0)
        entries = Array(entries.prefix(Self.limit))
        save()
        NSDocumentController.shared.noteNewRecentDocumentURL(location.url)
    }

    /// Remove one entry, which is what the interface offers after refusing to open a
    /// project that has gone.
    func forget(_ url: URL) {
        entries.removeAll { $0.url == url }
        save()
    }

    /// Entries whose file is no longer on disk.
    ///
    /// Reported rather than removed. A project on an unmounted external disk or a network
    /// share is *missing right now* and back tomorrow, and silently deleting the entry
    /// would lose the path the user needs in order to find it again. The welcome window
    /// dims them; forgetting stays something the person chooses.
    var vanished: Set<URL> {
        Set(entries.map(\.url).filter { !FileManager.default.fileExists(atPath: $0.path) })
    }

    private func save() {
        defaults.set(try? JSONEncoder().encode(entries), forKey: Self.key)
    }

    private static func load(from defaults: UserDefaults) -> [Entry] {
        guard let data = defaults.data(forKey: key),
              let decoded = try? JSONDecoder().decode([Entry].self, from: data)
        else { return [] }
        return Array(decoded.prefix(limit))
    }
}
