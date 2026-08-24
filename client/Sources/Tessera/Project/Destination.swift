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
    /// A course running in *this term*. The first destination whose contents depend on
    /// which term the toolbar has selected.
    case offerings
    case groups
    case constraints
    // The four that exist because the others need them. Under their own heading rather
    // than mixed in: a person setting up a project works down Data, and buildings before
    // rooms is the order that avoids a dead end.
    case buildings
    case features
    case departments
    case programs
    // The three the 2.5 console has always had and the application never did — found by
    // running 3.4's own exit test, which asks for parity with that console.
    case institutions
    case grids
    case terms
    case timetables

    var id: String { rawValue }

    /// The heading a group of destinations sits under. `nil` means the item stands alone
    /// at the top, which is what Overview does in every reference with a sidebar.
    var section: String? {
        switch self {
        case .overview: nil
        case .rooms, .instructors, .courses, .offerings, .groups, .constraints: "Data"
        case .buildings, .features, .departments, .programs,
             .institutions, .grids, .terms: "Setup"
        case .timetables: "Timetables"
        }
    }

    var title: String {
        switch self {
        case .overview: "Overview"
        case .rooms: "Rooms"
        case .instructors: "Instructors"
        case .courses: "Courses"
        case .offerings: "Offerings"
        case .groups: "Student Groups"
        case .constraints: "Constraints"
        case .timetables: "Timetables"
        case .buildings: "Buildings"
        case .features: "Features"
        case .departments: "Departments"
        case .programs: "Programmes"
        case .institutions: "Institution"
        case .grids: "Teaching Weeks"
        case .terms: "Terms"
        }
    }

    var symbol: String {
        switch self {
        case .overview: "square.grid.2x2"
        case .rooms: "door.left.hand.open"
        case .instructors: "person.2"
        case .courses: "books.vertical"
        case .offerings: "calendar.badge.clock"
        case .groups: "person.3"
        case .constraints: "slider.horizontal.3"
        case .timetables: "calendar"
        case .buildings: "building.2"
        case .features: "checklist"
        case .departments: "square.stack.3d.up"
        case .programs: "graduationcap"
        case .institutions: "building.columns"
        case .grids: "grid"
        case .terms: "calendar"
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
        case .offerings:
            ("Nothing offered this term", "An offering is a course being taught now. Add courses first, then offer them.")
        case .groups:
            ("No student groups yet", "Groups are a tree — a programme, its intakes, and the batches that split out of them.")
        case .constraints:
            ("Using the default rules", "Every term starts with a sensible set. Review them before generating.")
        case .timetables:
            ("No timetables yet", "Generate one once the term has rooms, instructors and courses.")
        case .buildings:
            ("No buildings yet", "A room belongs to a building, so add the first one here.")
        case .features:
            ("No features yet", "Projector, computers, a lab bench — what a session might require of a room.")
        case .departments:
            ("No departments yet", "Instructors and courses belong to one; add them here first.")
        case .programs:
            ("No programmes yet", "A programme is the root of a student group tree — B.Tech CSE, say.")
        case .institutions:
            ("No institution yet", "The university this file is about. Creating a project makes one.")
        case .grids:
            ("No teaching weeks yet", "A week says how many days there are, how they divide, and where lunch is.")
        case .terms:
            ("No terms yet", "A term is a period you build a timetable for — Autumn, say. It needs a teaching week first.")
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
        case .offerings: .offerings
        case .groups: .groups
        case .constraints: .constraints
        case .overview, .timetables: nil
        // Counted the same way, so the sidebar says how much setup is done.
        case .buildings: .buildings
        case .features: .features
        case .departments: .departments
        case .programs: .programs
        // Counted like the rest, so the sidebar keeps saying how much setup is done.
        case .institutions: .institutions
        case .grids: .grids
        case .terms: .terms
        }
    }
}
