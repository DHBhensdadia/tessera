import Foundation

/// Everywhere a project window can go.
///
/// One enum rather than a view hierarchy, so that navigation is a value: it can be stored
/// in `@SceneStorage` and restored on relaunch, it can be tested without a window, and a
/// screen added in 3.4 is a case here rather than a change to the shell.
///
/// The order is the order the sidebar shows, which is also the order P7 Act 4 asks people
/// to fill things in: rooms and instructors before the courses that need them, courses
/// before the constraints that talk about them.
enum Destination: String, CaseIterable, Identifiable, Sendable {
    case overview
    case rooms
    case instructors
    case courses
    case groups
    case constraints
    case timetables

    var id: String { rawValue }

    /// The heading a group of destinations sits under. `nil` means the item stands alone
    /// at the top, which is what Overview does in every reference with a sidebar.
    var section: String? {
        switch self {
        case .overview: nil
        case .rooms, .instructors, .courses, .groups, .constraints: "Data"
        case .timetables: "Timetables"
        }
    }

    var title: String {
        switch self {
        case .overview: "Overview"
        case .rooms: "Rooms"
        case .instructors: "Instructors"
        case .courses: "Courses"
        case .groups: "Student Groups"
        case .constraints: "Constraints"
        case .timetables: "Timetables"
        }
    }

    var symbol: String {
        switch self {
        case .overview: "square.grid.2x2"
        case .rooms: "door.left.hand.open"
        case .instructors: "person.2"
        case .courses: "books.vertical"
        case .groups: "person.3"
        case .constraints: "slider.horizontal.3"
        case .timetables: "calendar"
        }
    }

    /// What a screen says before it has anything to show.
    ///
    /// Written per destination rather than generated from the title, because "No rooms
    /// yet" and "No timetables yet" want different next actions, and an empty state whose
    /// only content is the word it is missing is the blank page it was supposed to replace.
    var emptyState: (title: String, explanation: String) {
        switch self {
        case .overview:
            ("Nothing to summarise yet", "Add rooms, instructors and courses, and this becomes the state of the term.")
        case .rooms:
            ("No rooms yet", "Import a spreadsheet, or add the first room by hand.")
        case .instructors:
            ("No instructors yet", "Import a staff list, or add people one at a time.")
        case .courses:
            ("No courses yet", "A course is what is taught; an offering is a course running in this term.")
        case .groups:
            ("No student groups yet", "Groups are a tree — a programme, its intakes, and the batches that split out of them.")
        case .constraints:
            ("Using the default rules", "Every term starts with a sensible set. Review them before generating.")
        case .timetables:
            ("No timetables yet", "Generate one once the term has rooms, instructors and courses.")
        }
    }

    /// Which count the sidebar shows beside this item, if any.
    ///
    /// Overview and Timetables have none: one is not a collection, and the other counts
    /// scenarios rather than records, which is 5.x's business.
    var countsEntity: ProjectSummary.Entity? {
        switch self {
        case .rooms: .rooms
        case .instructors: .instructors
        case .courses: .courses
        case .groups: .groups
        case .constraints: .constraints
        case .overview, .timetables: nil
        }
    }
}
