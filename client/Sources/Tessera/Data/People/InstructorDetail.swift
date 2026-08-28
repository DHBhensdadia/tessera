import DesignSystem
import SwiftUI

/// One instructor: who they are, and how much they can be asked to teach.
///
/// The load limits are the reason this screen is not a copy of Rooms. Each is optional, and
/// **blank means no limit** — so the field cannot simply parse to an `Int` and send it. Text
/// that is not a number is refused here, beside the field, without a request: the engine
/// would have no way to tell it apart from somebody deliberately clearing the limit.
struct InstructorDetail: View {
    let instructor: InstructorStore.Instructor
    let store: InstructorStore
    let availability: AvailabilityStore?
    let appearance: Appearance

    @State private var name = ""
    @State private var email = ""
    @State private var departmentID: Int?
    @State private var perDay = ""
    @State private var perWeek = ""
    @State private var consecutive = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Instructor", appearance: appearance) {
                Field(
                    label: "Name",
                    placeholder: "Prof. Sharma",
                    value: $name,
                    problem: store.problem(for: "name"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Email",
                    placeholder: "sharma@example.edu",
                    value: $email,
                    problem: store.problem(for: "email"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Chooser(
                    label: "Department",
                    options: store.departments,
                    selection: $departmentID,
                    emptyHint: "No departments yet — add one under Setup first.",
                    appearance: appearance
                )
                .onChange(of: departmentID) { commit() }

                Text("Press return to save. Tessera will say if the engine refuses.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }

            ContentSection("Teaching load", appearance: appearance) {
                Text("Leave a limit blank and the solver will not bound it.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))

                Field(
                    label: "At most, slots per day",
                    placeholder: "No limit",
                    value: $perDay,
                    problem: store.problem(for: "max_slots_per_day"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "At most, slots per week",
                    placeholder: "No limit",
                    value: $perWeek,
                    problem: store.problem(for: "max_slots_per_week"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "At most, consecutive slots",
                    placeholder: "No limit",
                    value: $consecutive,
                    problem: store.problem(for: "max_consecutive_slots"),
                    appearance: appearance
                )
                .onSubmit(commit)
            }

            AvailabilitySection(
                store: availability,
                subject: instructor.id,
                noun: "person",
                appearance: appearance
            )
        }
        .task(id: instructor.id) {
            name = instructor.name
            email = instructor.email
            departmentID = instructor.departmentID
            perDay = instructor.maxSlotsPerDay.map(String.init) ?? ""
            perWeek = instructor.maxSlotsPerWeek.map(String.init) ?? ""
            consecutive = instructor.maxConsecutiveSlots.map(String.init) ?? ""
        }
    }

    /// Send what is in the fields — unless a limit does not read as a number, in which case
    /// nothing is sent at all.
    ///
    /// Refusing the whole save rather than the one field is deliberate: a `PATCH` carrying
    /// five good values and one guess is a save that half worked, and the person would have
    /// to discover which half.
    private func commit() {
        var edited = instructor
        edited.name = name
        edited.email = email
        edited.departmentID = departmentID

        var readable = true
        func limit(_ text: String, _ field: String, into target: inout Int?) {
            switch NumberEntry.limit(text) {
            case .success(let value):
                store.complain(nil, about: field)
                target = value
            case .failure(let complaint):
                store.complain(complaint.message, about: field)
                readable = false
            }
        }

        limit(perDay, "max_slots_per_day", into: &edited.maxSlotsPerDay)
        limit(perWeek, "max_slots_per_week", into: &edited.maxSlotsPerWeek)
        limit(consecutive, "max_consecutive_slots", into: &edited.maxConsecutiveSlots)

        guard readable else { return }
        Task { await store.save(edited) }
    }
}
