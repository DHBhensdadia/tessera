import Foundation
import Testing

@testable import Tessera

/// That the difference between *make me one* and *open the one I had* survives the trip
/// from a menu item to a subprocess argument.
///
/// This is the only area of the shell where getting it wrong destroys something. The
/// engine creates whatever is missing, which is correct for a new project and quietly
/// destructive for a reopen: a stale entry in Recent Projects, or a window macOS restored
/// after the file moved to another disk, would produce an empty project under the original
/// name. It is one boolean and it is invisible when wrong.
struct ProjectIntentTests {
    @Test func reopeningAsksTheEngineToRefuseToCreateAnything() {
        let arguments = EngineController.arguments(
            for: ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"), intent: .reopen)
        )
        #expect(arguments.contains("--must-exist"))
    }

    @Test func creatingDoesNot() {
        let arguments = EngineController.arguments(
            for: ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"), intent: .create)
        )
        #expect(!arguments.contains("--must-exist"))
    }

    @Test func theProjectPathIsPassedUnescaped() {
        // A path with a space is the common case on a Mac — "Danger zone", "My Documents"
        // — and `URL.path` percent-encodes by default, which the engine would then open
        // as a literal `%20`.
        let arguments = EngineController.arguments(
            for: ProjectLocation(URL(filePath: "/tmp/Some Folder/Autumn.tessera"))
        )
        #expect(arguments.contains("/tmp/Some Folder/Autumn.tessera"))
    }
}

/// That a project which has gone is reported as a project which has gone.
struct ProjectProblemTests {
    private let somewhere = ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"))

    /// Mapped from the engine's exit status, not from the text of its log.
    ///
    /// The alternative — matching the message — is a coupling that survives exactly until
    /// somebody improves the wording, and this branch decides whether the application
    /// offers to delete an entry from the user's Recent Projects.
    @Test func theEngineSExitStatusNamesTheProblem() {
        #expect(ProjectProblem(exitStatus: 3, location: somewhere) == .missing(somewhere))
        #expect(ProjectProblem(exitStatus: 4, location: somewhere) == .notAProject(somewhere))
    }

    @Test func anyOtherStatusIsAnEngineFailureRatherThanTheUserSFile() {
        #expect(ProjectProblem(exitStatus: 1, location: somewhere) == nil)
        #expect(ProjectProblem(exitStatus: 0, location: somewhere) == nil)
    }

    /// Only a project that has genuinely gone is worth offering to forget; something at
    /// the path that is not ours might be the user pointing at the wrong thing.
    @Test func onlyAMissingProjectIsOfferedForForgetting() {
        #expect(ProjectProblem.missing(somewhere).offersToForget)
        #expect(!ProjectProblem.notAProject(somewhere).offersToForget)
    }
}

/// That a window is identified by *which project* it shows, and nothing else.
struct ProjectIdentityTests {
    /// `WindowGroup(for:)` keeps one window per value, which is what stops a second engine
    /// being started against a database that already has one.
    ///
    /// **The identity SwiftUI actually uses is the encoded form, not `==`.** The first
    /// version of this test asserted equality, passed, and the application still opened a
    /// second window and a second engine on one file — because the synthesised `Codable`
    /// encoded `intent`, and the same project arriving from a launch argument and from the
    /// Finder encoded differently. A guard aimed at the wrong mechanism.
    @Test func theSameProjectEncodesIdenticallyWhateverOpenedIt() throws {
        let fromFinder = ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"), intent: .reopen)
        var setup = ProjectSetup()
        setup.institution = "Somewhere"
        let fromSheet = ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"), intent: .create, setup: setup)

        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        #expect(try encoder.encode(fromFinder) == encoder.encode(fromSheet))
        #expect(fromFinder == fromSheet)
        #expect(fromFinder.hashValue == fromSheet.hashValue)
    }

    /// A window macOS restores after a relaunch must never create a project that has gone.
    @Test func aRestoredWindowDecodesAsAReopen() throws {
        let encoded = try JSONEncoder().encode(
            ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"), intent: .create, setup: ProjectSetup())
        )
        let restored = try JSONDecoder().decode(ProjectLocation.self, from: encoded)
        #expect(restored.intent == .reopen)
        #expect(restored.setup == nil)
    }

    @Test func pathsAreStandardisedSoTwoSpellingsAreOneProject() {
        let direct = ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"))
        let roundabout = ProjectLocation(URL(filePath: "/tmp/./Autumn.tessera"))
        #expect(direct == roundabout)
    }

    @Test func theWindowIsNamedAfterTheFileRatherThanThePath() {
        let location = ProjectLocation(URL(filePath: "/Users/x/Timetables/Autumn 2026.tessera"))
        #expect(location.name == "Autumn 2026")
    }
}

/// That one project gets one engine, however many times the interface asks.
///
/// Written after the shipped bundle started **six** engines for a single open project.
/// The controller lived in the window's `@State`, created in `init` — and SwiftUI
/// re-evaluates a view struct whenever anything upstream changes, so `init` ran over and
/// over and several of the controllers it made were started.
///
/// The engine's own rule since 2.9 is that one engine serves one project for its whole
/// life. That was written down, believed, and false in the product for as long as the
/// window owned the controller. It is now a property of the type that hands them out.
@MainActor
struct EngineRegistryTests {
    private let autumn = ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"))
    private let spring = ProjectLocation(URL(filePath: "/tmp/Spring.tessera"))

    @Test func askingTwiceForOneProjectGivesTheSameEngine() {
        let registry = EngineRegistry()
        #expect(registry.controller(for: autumn) === registry.controller(for: autumn))
        #expect(registry.count == 1)
    }

    /// Six calls, because six is the number the real application made.
    @Test func askingSixTimesStillGivesOne() {
        let registry = EngineRegistry()
        for _ in 0..<6 { _ = registry.controller(for: autumn) }
        #expect(registry.count == 1)
    }

    @Test func twoProjectsGetTwoEngines() {
        let registry = EngineRegistry()
        #expect(registry.controller(for: autumn) !== registry.controller(for: spring))
        #expect(registry.count == 2)
    }

    /// The same project reached by two routes is still one engine — which is the whole
    /// reason `ProjectLocation` excludes the intent from its identity.
    @Test func theRouteInDoesNotCreateASecondEngine() {
        let registry = EngineRegistry()
        let fromPanel = ProjectLocation(URL(filePath: "/tmp/Autumn.tessera"), intent: .create)
        _ = registry.controller(for: autumn)
        _ = registry.controller(for: fromPanel)
        #expect(registry.count == 1)
    }

    /// The close notification can arrive for a window whose engine has already gone —
    /// releasing twice must be a no-op rather than a crash.
    @Test func releasingTwiceIsHarmless() {
        let registry = EngineRegistry()
        _ = registry.controller(for: autumn)
        registry.release(autumn)
        registry.release(autumn)
        #expect(registry.count == 0)
    }

    @Test func closingAWindowReleasesItsEngine() {
        let registry = EngineRegistry()
        _ = registry.controller(for: autumn)
        _ = registry.controller(for: spring)
        registry.release(autumn)
        #expect(registry.count == 1)
        registry.release(spring)
        #expect(registry.count == 0)
    }
}

/// That the recent list behaves like a recent list.
@MainActor
struct RecentProjectsTests {
    private func store() -> RecentProjects {
        let suite = UserDefaults(suiteName: "recents-\(UUID().uuidString)")!
        return RecentProjects(defaults: suite)
    }

    @Test func themostRecentlyOpenedComesFirst() {
        let recents = store()
        recents.note(ProjectLocation(URL(filePath: "/tmp/A.tessera")))
        recents.note(ProjectLocation(URL(filePath: "/tmp/B.tessera")))
        #expect(recents.entries.first?.location.name == "B")
    }

    /// Reopening something already listed moves it up rather than listing it twice.
    @Test func openingSomethingAgainDoesNotDuplicateIt() {
        let recents = store()
        recents.note(ProjectLocation(URL(filePath: "/tmp/A.tessera")))
        recents.note(ProjectLocation(URL(filePath: "/tmp/B.tessera")))
        recents.note(ProjectLocation(URL(filePath: "/tmp/A.tessera")))
        #expect(recents.entries.count == 2)
        #expect(recents.entries.first?.location.name == "A")
    }

    @Test func theListIsBounded() {
        let recents = store()
        for index in 0..<20 {
            recents.note(ProjectLocation(URL(filePath: "/tmp/P\(index).tessera")))
        }
        #expect(recents.entries.count == RecentProjects.limit)
    }

    @Test func itSurvivesRelaunch() {
        let suite = UserDefaults(suiteName: "recents-\(UUID().uuidString)")!
        RecentProjects(defaults: suite).note(ProjectLocation(URL(filePath: "/tmp/A.tessera")))
        #expect(RecentProjects(defaults: suite).entries.first?.location.name == "A")
    }

    /// A project on an unmounted disk is *missing right now*, not gone. Reporting it
    /// without deleting it keeps the path the person needs in order to find it again.
    @Test func aVanishedProjectIsReportedRatherThanRemoved() {
        let recents = store()
        recents.note(ProjectLocation(URL(filePath: "/tmp/definitely-not-here.tessera")))
        #expect(recents.entries.count == 1)
        #expect(recents.vanished.count == 1)
    }
}

/// That the grid the sheet describes is the grid the engine is asked for.
struct TimeGridSetupTests {
    @Test func slotsFollowTheDayAndTheSlotLength() {
        var grid = TimeGridSetup()
        grid.startMinute = 9 * 60
        grid.endMinute = 17 * 60
        grid.slotMinutes = 30
        #expect(grid.slotsPerDay == 16)
        #expect(grid.slotsPerWeek == 80)
    }

    /// The number P7 insists is stated out loud: what is left after the breaks.
    @Test func breaksComeOutOfTheUsableCount() {
        var grid = TimeGridSetup()
        grid.breaks = [TimeGridSetup.BreakWindow(name: "Lunch", start: 13 * 60, end: 14 * 60)]
        #expect(grid.breakSlots == [8, 9])
        #expect(grid.usableSlotsPerDay == 14)
    }

    /// A break dragged past the end of teaching must not produce slot indices the grid
    /// would reject — the engine caps `slots_per_day` at 96 and validates the range.
    @Test func aBreakOutsideTheDayIsClamped() {
        var grid = TimeGridSetup()
        grid.breaks = [TimeGridSetup.BreakWindow(name: "Late", start: 20 * 60, end: 22 * 60)]
        #expect(grid.breakSlots.isEmpty)
    }

    @Test func everyBreakSlotIsInsideTheDay() {
        var grid = TimeGridSetup()
        grid.breaks = [
            TimeGridSetup.BreakWindow(name: "Early", start: 7 * 60, end: 10 * 60),
            TimeGridSetup.BreakWindow(name: "Lunch", start: 13 * 60, end: 14 * 60),
        ]
        #expect(grid.breakSlots.allSatisfy { (0..<grid.slotsPerDay).contains($0) })
    }

    /// The academic year runs July to June, so August is the start of a new one and
    /// February is still in the old one.
    @Test func theAcademicYearIsGuessedRatherThanAsked() {
        #expect(ProjectSetup.defaultAcademicYear.contains("–"))
    }

    @Test func theSavePanelSuggestsAName() {
        var setup = ProjectSetup()
        setup.institution = "Sardar Patel University"
        setup.termName = "Autumn"
        setup.academicYear = "2026–27"
        #expect(ProjectChooser.suggestedName(for: setup) == "Sardar Patel University — Autumn 2026–27")
    }

    @Test func anEmptySetupStillSuggestsSomethingUsable() {
        #expect(!ProjectChooser.suggestedName(for: ProjectSetup()).isEmpty)
    }
}
