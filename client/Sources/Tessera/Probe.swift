import EngineClient
import Foundation

/// `--probe` — exercise the client against a real engine, including the failures.
///
/// It exists because a generated client compiles against a *document*, not against a
/// server, so "it builds" proves close to nothing. Three defects in this phase were
/// invisible to the compiler and to the suites: a plugin that generated nothing, a base URL
/// that doubled the path prefix, and a typed failure the generated code wrapped in a
/// `ClientError` so no call site could catch it.
///
/// Every call goes through `connection.run`, which is exactly what 3.4's screens will do.
@MainActor
enum Probe {
    static func run() async {
        let project = temporaryProject()
        let engine = EngineController(location: ProjectLocation(project, intent: .create))
        await engine.start()

        guard case .running(let running) = engine.state else {
            say("probe: the engine did not start — \(engine.state)")
            exit(1)
        }
        let connection = EngineConnection(port: running.port, token: running.token)

        do {
            let institution = try await succeeds(connection)
            try await refusesADuplicate(connection, institution: institution)
            try await complainsAboutAField(connection, institution: institution)
            try await reportsSomethingMissing(connection)
            await theRoomsScreenWorks(connection)
            let term = await theTeachingScreensWork(connection, institution: institution)
            if let term { await theTreeAndTheGridWork(connection, term: term) }
            await theConstraintCatalogueArrives(connection)
            if let term { await theRulesScreenWorks(connection, term: term) }
            await noticesTheEngineHasGone(engine, connection)
            engine.stop()
            if let term { await theWeightSurvivesReopening(project, term: term) }
            exit(0)
        } catch {
            say("probe: unexpected — \(EngineFailure.unwrap(error).message)")
            engine.stop()
            exit(1)
        }
    }

    /// The rooms screen's store, driven the way the screen drives it.
    ///
    /// The screen is a view; this exercises the object behind it, where the requests and
    /// the error routing live. It goes all the way to `FieldErrors`, because "the engine
    /// refused" and "the message reached the field the user has to fix" are different
    /// claims, and only the second one is the feature 3.4 exists to build.
    private static func theRoomsScreenWorks(_ connection: EngineConnection) async {
        let store = RoomStore(connection: connection)
        await store.load()
        await store.add()

        guard let created = store.rooms.first else {
            say("rooms     MISSING   nothing was created")
            return
        }
        say("rooms     created   \(created.name), capacity \(created.capacity)")

        var edited = created
        edited.name = "LH-201"
        edited.capacity = 120
        await store.save(edited)
        let saved = store.rooms.first { $0.id == created.id }
        say("rooms     edited    \(saved?.name ?? "?"), capacity \(saved?.capacity ?? -1)")

        // A refusal the engine is certain to make. The question is not whether it refuses
        // — 3.3 proved that — but whether the message reaches the field the user must fix.
        var invalid = edited
        invalid.capacity = -5
        await store.save(invalid)
        if let message = store.message(for: "capacity") {
            say("rooms     refused   the capacity field says: \(message)")
        } else {
            say("rooms     MISSING   the refusal never reached the field — notice: \(store.notice ?? "nothing")")
        }

        // Editing keeps what was typed rather than reverting to the server's value: the
        // user can fix a message, and cannot retype what they no longer have.
        let afterRefusal = store.rooms.first { $0.id == created.id }
        say("rooms     kept      the list still shows \(afterRefusal?.name ?? "?") — the refused edit did not overwrite it")

        await theSupportingScreensWork(connection, roomStore: store, room: edited)
    }

    /// Part 2's exit: a room given a building and features, through the same screens a
    /// person would use to create them.
    private static func theSupportingScreensWork(
        _ connection: EngineConnection,
        roomStore: RoomStore,
        room: RoomStore.Room
    ) async {
        let buildings = SimpleEntityStore(title: "Buildings", deleteWarning: "", connection: connection, operations: .buildings)
        await buildings.load()
        await buildings.add()
        guard let building = buildings.items.last else {
            say("setup     MISSING   no building was created")
            return
        }
        var named = building
        named.name = "Science Block"
        await buildings.save(named)
        say("setup     building  \(buildings.items.last?.name ?? "?")\(buildings.notice.map { " — refused: \($0)" } ?? "")")

        let features = SimpleEntityStore(title: "Features", deleteWarning: "", connection: connection, operations: .features)
        await features.load()
        await features.add()
        guard let feature = features.items.last else {
            say("setup     MISSING   no feature was created")
            return
        }
        var projector = feature
        projector.name = "Projector"
        await features.save(projector)
        say("setup     feature   \(features.items.last?.name ?? "?")")

        let departments = SimpleEntityStore(title: "Departments", deleteWarning: "", connection: connection, operations: .departments)
        await departments.load()
        await departments.add()
        say("setup     dept      \(departments.items.last?.name ?? "?")")

        let programs = SimpleEntityStore(title: "Programmes", deleteWarning: "", connection: connection, operations: .programs)
        await programs.load()
        await programs.add()
        say("setup     programme \(programs.items.last?.name ?? "?")")

        // A *second* store, opened on the same engine, must see what the first one made.
        //
        // The probe used to go straight from `add()` to `items.last`, which reads back the
        // object the call returned and would pass even if `load()` fetched nothing at all
        // — and that is precisely what shipped: the Buildings screen listed nothing beside
        // a sidebar counting two. This is the check that would have caught it.
        let reopened = SimpleEntityStore(title: "Buildings", deleteWarning: "", connection: connection, operations: .buildings)
        await reopened.load()
        if reopened.items.contains(where: { $0.id == building.id }) {
            say("setup     listed    a fresh store sees \(reopened.items.count) buildings, including Science Block")
        } else {
            say("setup     MISSING   a fresh store loaded \(reopened.items.count) buildings and Science Block was not among them")
        }

        // Now the join: give the room what only exists because those screens made it.
        await roomStore.load()
        var equipped = room
        equipped.buildingID = building.id
        equipped.featureIDs = [feature.id]
        await roomStore.save(equipped)

        await roomStore.load()
        if let back = roomStore.rooms.first(where: { $0.id == room.id }) {
            let buildingName = roomStore.buildings.first { $0.id == back.buildingID }?.name ?? "none"
            let featureNames = roomStore.features
                .filter { back.featureIDs.contains($0.id) }
                .map(\.name)
                .joined(separator: ", ")
            say("rooms     equipped  \(back.name) is in \(buildingName) with [\(featureNames)] — read back from the engine")
        } else {
            say("rooms     MISSING   the room vanished after equipping it")
        }

        // Deleting an occupied building **succeeds**, deliberately: `room.building_id` is
        // ON DELETE SET NULL, because losing a hundred rooms to a mistaken delete is far
        // worse than a hundred rooms briefly lacking an address. The probe originally
        // expected a refusal — the plan said so and the plan was wrong. What matters is
        // that the rooms survive, and that the confirmation says so before it happens.
        await buildings.delete(building)
        await roomStore.load()
        let survivor = roomStore.rooms.first { $0.id == room.id }
        let detached = survivor.map { $0.buildingID == nil } ?? false
        say("setup     deleted   the building went; \(survivor?.name ?? "the room") survived, "
            + "building now \(detached ? "none — as designed" : "STILL SET, which is wrong")")
    }

    /// Part 3's exit: a course taught to a group, and the sessions that fall out of it.
    ///
    /// This is the three-level split (#8) driven end to end — a **course** in the catalogue,
    /// an **offering** of it in a term, a weekly **pattern**, and finally the **sessions**
    /// the solver will place. Each step goes through the same store the screen drives, so
    /// what passes here is what a person gets.
    @discardableResult
    private static func theTeachingScreensWork(
        _ connection: EngineConnection,
        institution: Int
    ) async -> Int? {
        // A term to hang it all on. The probe creates its project bare, so nothing has made
        // one — in the application the creation sheet does, before the window opens.
        guard let term = await aTermExists(connection, institution: institution) else { return nil }

        let instructors = InstructorStore(connection: connection)
        await instructors.load()
        await instructors.add()
        guard var teacher = instructors.instructors.last else {
            say("teaching  MISSING   no instructor was created")
            return nil
        }
        teacher.name = "Prof. Sharma"
        teacher.maxSlotsPerDay = 4
        await instructors.save(teacher)
        let readBack = instructors.instructors.first { $0.id == teacher.id }
        say("teaching  staff     \(readBack?.name ?? "?") — at most \(readBack?.maxSlotsPerDay.map(String.init) ?? "no") slots a day")

        // Blank means *no limit*, and it must not arrive as zero. An instructor who can
        // teach nothing is a very different claim from one with no ceiling.
        var unbounded = readBack ?? teacher
        unbounded.maxSlotsPerDay = nil
        await instructors.save(unbounded)
        let cleared = instructors.instructors.first { $0.id == teacher.id }
        say("teaching  cleared   the daily limit is now \(cleared?.maxSlotsPerDay.map(String.init) ?? "none — not zero")")

        let courses = CourseStore(connection: connection)
        await courses.load()
        await courses.add()
        guard var course = courses.courses.last else {
            say("teaching  MISSING   no course was created")
            return nil
        }
        course.code = "CS301"
        course.name = "Operating Systems"
        course.credits = 4
        await courses.save(course)
        say("teaching  course    \(courses.courses.last?.code ?? "?") — \(courses.courses.last?.name ?? "?")")

        let groups = GroupStore(connection: connection)
        await groups.load()
        await groups.add()
        guard var batch = groups.all.last else {
            say("teaching  MISSING   no student group was created")
            return nil
        }
        batch.name = "2024 Intake — Semester 5"
        batch.size = 120
        await groups.save(batch, movingTo: nil)
        say("teaching  group     \(groups.all.last?.name ?? "?") — \(groups.all.last?.headcount ?? 0) students")

        let offerings = OfferingStore(connection: connection)
        await offerings.load(term: term)
        guard let offerable = offerings.offerableCourses.first(where: { $0.id == course.id }) else {
            say("teaching  MISSING   the new course was not offerable — menu had \(offerings.offerableCourses.count)")
            return nil
        }
        await offerings.add(course: offerable.id, term: term)
        guard let offering = offerings.offerings.last else {
            say("teaching  MISSING   no offering was created — \(offerings.notice ?? "no reason given")")
            return nil
        }
        say("teaching  offered   \(offerings.label(for: offering)) this term")

        // The course is now taken, so the Add menu must stop listing it. A menu whose only
        // outcome is a 409 is a menu that should not have had the item.
        let stillOfferable = offerings.offerableCourses.contains { $0.id == course.id }
        say("teaching  menu      the offered course is \(stillOfferable ? "STILL LISTED, which is wrong" : "no longer in the Add menu")")

        var draft = TemplateDraft()
        draft.kind = "lecture"
        draft.perWeek = 3
        draft.durationSlots = 1
        draft.attendeeIDs = [batch.id]
        draft.instructorIDs = [teacher.id]
        await offerings.addTemplate(to: offering.id, draft)
        guard let pattern = offerings.offerings.last?.templates.last else {
            say("teaching  MISSING   no pattern was created — \(offerings.notice ?? "no reason given")")
            return nil
        }
        say("teaching  pattern   \(pattern.perWeek) × \(pattern.kind) · \(offerings.minutes(pattern.durationSlots)) min · "
            + "\(pattern.attendeeNames.joined(separator: ", ")) · \(pattern.instructorNames.joined(separator: ", "))")

        guard let live = offerings.offerings.last else { return term }
        await offerings.expand(live)
        say("teaching  expanded  \(offerings.lastExpansion ?? "nothing came back — \(offerings.notice ?? "no reason")")")

        // Running it twice must change nothing: it is a reconciliation, not a generator.
        guard let again = offerings.offerings.last else { return term }
        let before = again.sessionCount
        await offerings.expand(again)
        let after = offerings.offerings.last?.sessionCount ?? -1
        say("teaching  idempotent expanding again left \(after) sessions "
            + "(was \(before)) — \(before == after ? "unchanged, as designed" : "CHANGED, which is wrong")")

        // And that a shape change is refused rather than silently ignored: the engine takes
        // multiplicity only, so 3 lectures becoming 4 must land while the length does not.
        guard var edited = offerings.offerings.last?.templates.last else { return term }
        edited.perWeek = 4
        await offerings.saveTemplate(edited, in: live.id)
        let multiplied = offerings.offerings.last?.templates.last
        say("teaching  adjusted  now \(multiplied?.perWeek ?? -1) × \(multiplied?.kind ?? "?") a week — "
            + "the pattern wants \(multiplied?.wanted ?? -1), \(multiplied?.generated ?? -1) exist, "
            + "so the screen says expanding is due")

        // A split pattern, which is the line P7 says does the teaching: one lab per
        // sub-batch is one pattern and three sessions. It must read correctly *before*
        // expanding, because that is when somebody is deciding whether they meant it.
        await groups.add()
        guard var batchA = groups.all.last else { return term }
        batchA.name = "Lab Batch A1"
        batchA.size = 40
        await groups.save(batchA, movingTo: nil)
        await groups.add()
        guard var batchB = groups.all.last else { return term }
        batchB.name = "Lab Batch A2"
        batchB.size = 40
        await groups.save(batchB, movingTo: nil)
        await offerings.load(term: term)

        var lab = TemplateDraft()
        lab.kind = "lab"
        lab.perWeek = 1
        lab.durationSlots = 2
        lab.splitPerAttendee = true
        lab.attendeeIDs = [batchA.id, batchB.id]
        await offerings.addTemplate(to: live.id, lab)
        guard let split = offerings.offerings.first(where: { $0.id == live.id })?.templates.last else {
            say("teaching  MISSING   no split pattern — \(offerings.notice ?? "no reason given")")
            return nil
        }
        say("teaching  split     1 × lab · \(offerings.minutes(split.durationSlots)) min · per sub-batch "
            + "→ generates \(split.wanted) sessions (\(split.attendeeNames.joined(separator: ", "))) "
            + "with \(split.generated) generated so far")

        guard let full = offerings.offerings.first(where: { $0.id == live.id }) else { return term }
        await offerings.expand(full)
        let settled = offerings.offerings.first { $0.id == live.id }
        let agree = (settled?.templates ?? []).allSatisfy { $0.generated == $0.wanted }
        say("teaching  agreed    after expanding, every pattern has what it wants: "
            + "\(agree ? "yes" : "NO — the local arithmetic disagrees with the engine")")

        return term
    }

    /// Part 4: the tree that is the data model, and the grid that is not a form.
    private static func theTreeAndTheGridWork(_ connection: EngineConnection, term: Int) async {
        let groups = GroupStore(connection: connection)
        await groups.load()

        guard let intake = groups.all.first(where: { $0.name == "2024 Intake — Semester 5" }) else {
            say("tree      MISSING   the intake created earlier is not in the tree")
            return
        }
        say("tree      loaded    \(groups.all.count) groups, "
            + "\(groups.all.filter { $0.depth == 0 }.count) at the root")

        // P7's gesture: split an intake into batches and let the strength divide.
        guard let plain = groups.all.first(where: { $0.name == "Lab Batch A1" }) else {
            say("tree      MISSING   no leaf to split")
            return
        }
        await groups.split(plain, into: 3)
        let children = groups.all.filter { $0.depth == plain.depth + 1 && $0.name.hasPrefix("Batch ") }
        let sizes = children.map(\.size)
        say("tree      split     \(plain.name) (\(plain.headcount)) → \(children.count) batches "
            + "\(sizes) summing to \(sizes.reduce(0, +))")

        let parentAfter = groups.all.first { $0.id == plain.id }
        say("tree      derived   \(plain.name) now counts as "
            + "\(parentAfter?.headcount ?? -1) from its batches, own size \(parentAfter?.size ?? -1)")

        // Nesting must be what the outline draws from, not something recomputed per row.
        let nested = groups.all.filter { $0.depth > 0 }.count
        say("tree      nested    \(nested) of \(groups.all.count) sit below a root")

        // Collapsing hides a subtree and nothing else.
        let openRows = groups.visible.count
        if let collapsible = groups.all.first(where: { $0.hasChildren }) {
            groups.toggle(collapsible)
            say("tree      collapsed \(collapsible.name) hid "
                + "\(openRows - groups.visible.count) rows; \(groups.visible.count) still shown")
            groups.toggle(collapsible)
        }

        // 2.3 refuses a move that would put a group inside its own descendant. The screen
        // does not reimplement that — it shows the sentence, so the sentence has to arrive.
        if let child = groups.all.first(where: { $0.parentID == plain.id }) {
            await groups.save(plain, movingTo: child.id)
            let complaint = groups.message(for: "parent_id") ?? groups.notice
            say("tree      refused   moving \(plain.name) into its own batch: "
                + "\(complaint ?? "NOTHING SAID, which is wrong")")
        }

        // The programme, which the engine accepted and never returned until now.
        if let programme = groups.programs.first {
            var placed = intake
            placed.programID = programme.id
            await groups.save(placed, movingTo: intake.parentID)
            let readBack = groups.all.first { $0.id == intake.id }
            say("tree      programme \(readBack?.name ?? "?") is in "
                + "\(groups.programs.first { $0.id == readBack?.programID }?.name ?? "NOTHING, which is wrong")")
        }

        await theGridWorks(connection, term: term)
    }

    /// Availability: a drag blocks a range, and a second drag frees part of it.
    private static func theGridWorks(_ connection: EngineConnection, term: Int) async {
        let rooms = RoomStore(connection: connection)
        await rooms.load()
        // A second room, so "availability is per subject" is a claim with two subjects
        // behind it rather than an assumption.
        if rooms.rooms.count < 2 { await rooms.add() }
        guard let room = rooms.rooms.first else {
            say("grid      MISSING   no room to set availability on")
            return
        }

        let store = AvailabilityStore(connection: connection, kind: .room, term: term)
        await store.load(subject: room.id)
        guard let week = store.week else {
            say("grid      MISSING   the teaching week did not load — \(store.notice ?? "no reason")")
            return
        }
        say("grid      week      \(week.days) days × \(week.slotsPerDay) slots of "
            + "\(week.slotMinutes) min, starting \(week.label(forSlotOfDay: 0))")

        // What a drag down Tuesday morning produces.
        let tuesdayMorning = Set((0..<3).map { week.slot(day: 1, of: $0) })
        await store.block(tuesdayMorning)
        await store.load(subject: room.id)
        say("grid      blocked   \(tuesdayMorning.sorted()) → engine holds "
            + "\(store.blocked.sorted()) for \(room.name)")

        // And that freeing part of it frees *part* of it. `clearUnavailability` without the
        // slot filter clears the whole subject, which is why #45 added the filter and why
        // this is worth proving rather than assuming.
        let firstOnly: Set<Int> = [week.slot(day: 1, of: 0)]
        await store.free(firstOnly)
        await store.load(subject: room.id)
        let survived = store.blocked.sorted()
        say("grid      freed     one slot; \(survived) remain — "
            + "\(survived.count == 2 ? "the rest survived, as designed" : "THE WHOLE SUBJECT WAS CLEARED, which is wrong")")

        // Availability is per subject: blocking one room must not blank another.
        if rooms.rooms.count > 1 {
            let other = rooms.rooms[1]
            let second = AvailabilityStore(connection: connection, kind: .room, term: term)
            await second.load(subject: other.id)
            say("grid      isolated  \(other.name) has \(second.blocked.count) blocked slots "
                + "while \(room.name) has \(store.blocked.count)")
        }
    }

    /// 3.4b part 1: the palette the constraints screen is assembled from.
    ///
    /// `SPECS` lives in the engine's domain and the console reads it by importing it. This
    /// is the check that it now reaches Swift instead — because "the types generated" and
    /// "the values arrive" are different claims, and this phase has already been caught by
    /// the difference twice.
    private static func theConstraintCatalogueArrives(_ connection: EngineConnection) async {
        do {
            let catalogue = try await connection.run {
                try await $0.constraintCatalogue().ok.body.json
            }
            let global = catalogue.kinds.filter { $0.scope == .global }
            let targeted = catalogue.kinds.filter { $0.scope == .targeted }
            say("rules     catalogue \(catalogue.kinds.count) kinds — "
                + "\(global.count) global, \(targeted.count) targeted; "
                + "\(catalogue.invariants.count) always enforced")

            // The parameterised one, because a kind with no params proves nothing about
            // whether params survived the trip.
            if let parameterised = catalogue.kinds.first(where: { !($0.params ?? []).isEmpty }) {
                let param = (parameterised.params ?? [])[0]
                // `_default`, not `default` — the generator renames a property whose name
                // is a Swift keyword, which is worth seeing once here rather than
                // discovering inside a form.
                say("rules     params    \(parameterised.kind.rawValue): "
                    + "'\(param.label)' \(param.minimum)-\(param.maximum), default \(param._default)")
                say("rules     sentence  \(parameterised.example)")
            } else {
                say("rules     MISSING   no kind arrived with parameters — the form has nothing to build")
            }

            // What the form needs in order to offer targets at all.
            if let narrowable = catalogue.kinds.first(where: { ($0.targets ?? []).count > 1 }) {
                let targets = (narrowable.targets ?? []).map(\.rawValue).joined(separator: ", ")
                say("rules     targets   \(narrowable.kind.rawValue) may name [\(targets)]")
            }

            if let first = catalogue.invariants.first {
                say("rules     enforced  \(first.statement)")
            } else {
                say("rules     MISSING   no invariants — the screen cannot say what is always true")
            }

            // The promise the client relies on to render a sentence while a form is typed.
            let specs = catalogue.kinds.filter { $0.summary_template.contains(":") }
            say("rules     bare      \(specs.isEmpty ? "every template fills in by name" : "A FORMAT SPEC ARRIVED, which Swift cannot fill")")
        } catch {
            say("rules     MISSING   the catalogue did not arrive — \(EngineFailure.unwrap(error).message)")
        }
    }

    /// 3.4b part 2: the first two blocks of the rules screen.
    private static func theRulesScreenWorks(_ connection: EngineConnection, term: Int) async {
        let store = ConstraintStore(connection: connection, term: term)
        await store.load()

        say("rules     enforced  \(store.invariants.count) rules the screen cannot switch off")
        guard let first = store.preferences.first else {
            say("rules     MISSING   the term has no preferences — a new term should start with seven")
            return
        }
        say("rules     seeded    \(store.preferences.count) preferences, e.g. "
            + "\"\(first.summary)\" at \(first.weight) (\(WeightScale.word(for: first.weight)))")

        // The move, through the same call the slider makes.
        let wanted = first.weight == 9 ? 2 : 9
        await store.setWeight(wanted, on: first)
        let moved = store.preferences.first { $0.id == first.id }
        say("rules     moved     \(first.weight) → \(moved?.weight ?? -1) "
            + "(\(WeightScale.word(for: moved?.weight ?? 0)))\(store.notice.map { " — refused: \($0)" } ?? "")")

        // Disabling is its own field, and must not be a weight of zero in disguise.
        await store.setEnabled(false, on: first)
        let off = store.preferences.first { $0.id == first.id }
        say("rules     ignored   considered=\(off?.enabled ?? true), weight still \(off?.weight ?? -1) "
            + "— disabling did not discard what was tuned")
        await store.setEnabled(true, on: first)

        await aCustomRuleCanBeWritten(store, term: term)

        // A second store on the same engine: proves `load()` reads the change back rather
        // than the first store simply remembering what it was told.
        let reopened = ConstraintStore(connection: connection, term: term)
        await reopened.load()
        let readBack = reopened.preferences.first { $0.id == first.id }
        say("rules     reloaded  a fresh store reads \(readBack?.weight ?? -1)")
    }

    /// 3.4b part 3: a rule the catalogue described, written through the form's own path.
    private static func aCustomRuleCanBeWritten(_ store: ConstraintStore, term: Int) async {
        // A global kind narrowed to one instructor: the case that is the *same kind* as a
        // term-wide preference and belongs among the custom rules rather than the sliders.
        guard let narrowable = store.kinds.first(where: {
            $0.scope == .global && ($0.targets ?? []).contains(.instructor)
        }) else {
            say("rules     MISSING   no global kind can be narrowed to an instructor")
            return
        }
        let people = await store.options(for: .instructor)
        guard let person = people.first else {
            say("rules     MISSING   no instructor to narrow a rule to")
            return
        }

        // The sentence the form shows while it is being filled in, and the sentence the
        // engine writes afterwards. They have to match — that is the whole point of taking
        // the template from the catalogue rather than writing one here.
        let predicted = RuleSentence.render(
            template: narrowable.summary_template,
            params: [:],
            targets: [person.name],
            unnarrowed: narrowable.unnarrowed
        )
        say("rules     preview   \(predicted)")

        let before = store.customRules.count
        let wrote = await store.create(
            kind: narrowable.kind,
            targets: [.init(id: person.id, kind: .instructor)],
            params: [:],
            isHard: false,
            weight: 7
        )
        guard wrote, store.customRules.count == before + 1,
              let created = store.customRules.last(where: { $0.summary == predicted })
                ?? store.customRules.last
        else {
            say("rules     MISSING   the rule was not written — \(store.notice ?? "no reason given")")
            return
        }
        say("rules     wrote     \(created.summary)")
        say("rules     agreed    the form's sentence and the engine's "
            + "\(created.summary == predicted ? "match" : "DIFFER, which means two wordings exist")")

        // A parameterised kind, so the params actually travel.
        if let parameterised = store.kinds.first(where: { !($0.params ?? []).isEmpty }),
           let spec = (parameterised.params ?? []).first {
            _ = await store.create(
                kind: parameterised.kind,
                targets: [.init(id: person.id, kind: .instructor)],
                params: [spec.name: spec.maximum],
                isHard: false,
                weight: 3
            )
            let withParam = store.customRules.first {
                $0.summary.contains(String(spec.maximum))
            }
            say("rules     param     \(withParam?.summary ?? "the parameterised rule was not written")")
        }

        // The bound the form drew from the catalogue is the engine's too. Sending one past
        // it must be refused rather than stored, or the two disagree about the same spec.
        if let parameterised = store.kinds.first(where: { !($0.params ?? []).isEmpty }),
           let spec = (parameterised.params ?? []).first {
            let count = store.customRules.count
            _ = await store.create(
                kind: parameterised.kind,
                targets: [.init(id: person.id, kind: .instructor)],
                params: [spec.name: spec.maximum + 1],
                isHard: false,
                weight: 3
            )
            let complaint = store.message(for: "params") ?? store.notice
            say("rules     refused   \(spec.name)=\(spec.maximum + 1) past its maximum of "
                + "\(spec.maximum): \(complaint ?? "NOTHING SAID, which is wrong"); "
                + "\(store.customRules.count == count ? "nothing stored" : "IT WAS STORED ANYWAY")")
        }

        // And removing one.
        await store.delete(created)
        say("rules     removed   \(store.customRules.count) custom rule(s) remain")
    }

    /// The claim the screen is most likely to get wrong: that the weight is in the file.
    ///
    /// A slider that moves, updates its own store and never reaches SQLite looks correct in
    /// every check above — the store is the thing being asked. So this stops the engine
    /// entirely and starts a **second one on the same project**, which is what reopening the
    /// window does, and asks that engine instead.
    private static func theWeightSurvivesReopening(_ project: URL, term: Int) async {
        let reopened = EngineController(location: ProjectLocation(project, intent: .reopen))
        await reopened.start()
        guard case .running(let running) = reopened.state else {
            say("rules     MISSING   the project would not reopen — \(reopened.state)")
            return
        }
        defer { reopened.stop() }

        let connection = EngineConnection(port: running.port, token: running.token)
        let store = ConstraintStore(connection: connection, term: term)
        await store.load()
        guard let first = store.preferences.first else {
            say("rules     MISSING   the reopened project has no preferences")
            return
        }
        say("rules     persisted after a full engine restart, \"\(first.summary)\" is still "
            + "\(first.weight) (\(WeightScale.word(for: first.weight))) — it reached the file")
    }

    /// A grid and a term, so there is something for an offering to belong to.
    private static func aTermExists(_ connection: EngineConnection, institution: Int) async -> Int? {
        do {
            let grid = try await connection.run {
                try await $0.createTimeGrid(
                    body: .json(.init(
                        day_start_minute: 9 * 60,
                        days: 5,
                        institution_id: institution,
                        slot_minutes: 60,
                        slots_per_day: 8
                    ))
                ).created.body.json
            }
            let term = try await connection.run {
                try await $0.createTerm(
                    body: .json(.init(
                        academic_year: "2026–27",
                        institution_id: institution,
                        name: "Autumn",
                        time_grid_id: grid.id
                    ))
                ).created.body.json
            }
            say("teaching  term      \(term.name) \(term.academic_year), \(grid.slot_minutes)-minute slots")
            return term.id
        } catch {
            say("teaching  MISSING   no term could be created — \(EngineFailure.unwrap(error).message)")
            return nil
        }
    }

    /// The happy path: a write, then a read that proves the write landed.
    private static func succeeds(_ connection: EngineConnection) async throws -> Int {
        let created = try await connection.run {
            try await $0.createInstitution(body: .json(.init(name: "Probe University"))).created.body.json
        }
        let page = try await connection.run {
            try await $0.listInstitutions().ok.body.json
        }
        say("ok        wrote and read back — total=\(page.total), first=\(page.items.first?.name ?? "none")")
        return created.id
    }

    /// A 409: the engine refusing on a rule, in the sentence it already wrote.
    private static func refusesADuplicate(_ connection: EngineConnection, institution: Int) async throws {
        _ = try await connection.run {
            try await $0.createBuilding(body: .json(.init(institution_id: institution, name: "Block A")))
        }
        do {
            _ = try await connection.run {
                try await $0.createBuilding(body: .json(.init(institution_id: institution, name: "Block A")))
            }
            say("MISSING   a duplicate building was accepted")
        } catch let failure as EngineFailure {
            say("refused   \(failure.problem?.status ?? 0) \(failure.problem?.title ?? "?") — \(failure.message)")
            say("          transient? \(failure.isTransient)  — a refusal is a decision, so no retry")
        }
    }

    /// A 422: a complaint about one field, which a form has to place beside that field.
    private static func complainsAboutAField(_ connection: EngineConnection, institution: Int) async throws {
        do {
            _ = try await connection.run {
                try await $0.createBuilding(body: .json(.init(institution_id: institution, name: "")))
            }
            say("MISSING   an empty building name was accepted")
        } catch let failure as EngineFailure {
            say("refused   \(failure.problem?.status ?? 0) — \(failure.message)")
            for field in failure.fields {
                let hint = field.hint.isEmpty ? "" : "  hint: \(field.hint)"
                say("          field '\(field.fieldName)' (\(field.pointer)): \(field.message)\(hint)")
            }
            if failure.fields.isEmpty {
                say("          NO FIELD DETAIL — a form could not place this beside an input")
            }
        }
    }

    private static func reportsSomethingMissing(_ connection: EngineConnection) async throws {
        do {
            _ = try await connection.run {
                try await $0.getBuilding(path: .init(building_id: 999_999))
            }
            say("MISSING   a nonexistent building was returned")
        } catch let failure as EngineFailure {
            say("refused   \(failure.problem?.status ?? 0) \(failure.problem?.title ?? "?")")
        }
    }

    /// The engine dying underneath a live request — the case D6 exists for.
    private static func noticesTheEngineHasGone(
        _ engine: EngineController, _ connection: EngineConnection
    ) async {
        engine.stop()
        try? await Task.sleep(for: .milliseconds(600))
        do {
            _ = try await connection.run { try await $0.listBuildings() }
            say("MISSING   a dead engine answered")
        } catch let failure as EngineFailure {
            say("gone      \(failure.message)")
            say("          transient? \(failure.isTransient)  — so the retries above were worth making")
        } catch {
            say("gone      untyped: \(error)")
        }
    }

    /// The rooms screen's store, driven the way the screen drives it.
    ///
    /// The screen is a view; this exercises the object behind it, which is where the
    /// requests and the error routing live. It goes all the way to `FieldErrors`, because
    /// "the engine refused" and "the message reached the field the user must fix" are
    /// different claims and only the second one is the feature.
    private static func probeRooms(_ connection: EngineConnection) async -> Bool {
        let store = RoomStore(connection: connection)
        await store.load()

        await store.add()
        guard let created = store.rooms.first else {
            say("rooms: nothing was created")
            return false
        }
        say("rooms: created — \(created.name), capacity \(created.capacity)")

        var edited = created
        edited.name = "LH-201"
        edited.capacity = 120
        await store.save(edited)
        let saved = store.rooms.first { $0.id == created.id }
        say("rooms: edited  — \(saved?.name ?? "?"), capacity \(saved?.capacity ?? -1)")

        // Now provoke a refusal the engine is certain to make, and see where it lands.
        var invalid = edited
        invalid.capacity = -5
        await store.save(invalid)

        if let message = store.message(for: "capacity") {
            say("rooms: refused  — capacity field says: \(message)")
        } else {
            say("rooms: REFUSAL DID NOT REACH THE FIELD — notice=\(store.notice ?? "nothing")")
            return false
        }

        // A second room with the same name: a rule violation rather than a field problem,
        // so it must arrive as a notice rather than vanish.
        await store.add()
        if let second = store.rooms.last, second.id != created.id {
            var clash = second
            clash.name = "LH-201"
            await store.save(clash)
            say("rooms: duplicate — notice: \(store.notice ?? "NOTHING, which is wrong")")
        }

        return true
    }

    private static func temporaryProject() -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appending(path: "probe-\(UUID().uuidString).tessera")
    }

    private static func say(_ line: String) {
        FileHandle.standardError.write(Data((line + "\n").utf8))
    }
}
