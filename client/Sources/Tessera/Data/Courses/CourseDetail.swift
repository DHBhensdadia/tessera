import DesignSystem
import SwiftUI

/// One course in the catalogue.
struct CourseDetail: View {
    let course: CourseStore.Course
    let store: CourseStore
    let appearance: Appearance

    @State private var code = ""
    @State private var name = ""
    @State private var credits = ""
    @State private var departmentID: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Course", appearance: appearance) {
                Field(
                    label: "Code",
                    placeholder: "CS301",
                    value: $code,
                    problem: store.problem(for: "code"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Name",
                    placeholder: "Operating Systems",
                    value: $name,
                    problem: store.problem(for: "name"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Credits",
                    placeholder: "4",
                    value: $credits,
                    problem: store.problem(for: "credits"),
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
        }
        .task(id: course.id) {
            code = course.code
            name = course.name
            credits = String(course.credits)
            departmentID = course.departmentID
        }
    }

    private func commit() {
        var edited = course
        edited.code = code
        edited.name = name
        edited.departmentID = departmentID

        switch NumberEntry.count(credits) {
        case .success(let value):
            store.complain(nil, about: "credits")
            edited.credits = value
        case .failure(let complaint):
            store.complain(complaint.message, about: "credits")
            return
        }
        Task { await store.save(edited) }
    }
}
