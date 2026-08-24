import DesignSystem
import SwiftUI

/// One room, and everything about it that can be changed.
///
/// The detail view owns the fields and nothing else — no networking, no list behaviour, no
/// deletion. That split is what lets `EntityWorkspace` be built once: what an item *is*
/// lives here, and how a list of them behaves lives there.
///
/// Saving happens on commit rather than on keystroke (D3). A local copy is edited freely
/// and sent when a field is finished with, which is what `onSubmit` and losing focus mean.
struct RoomDetail: View {
    let room: RoomStore.Room
    let store: RoomStore
    let availability: AvailabilityStore?
    let appearance: Appearance

    @State private var name: String = ""
    @State private var capacity: String = ""
    @State private var buildingID: Int?
    @State private var featureIDs: Set<Int> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ContentSection("Room", appearance: appearance) {
                Field(
                    label: "Name",
                    placeholder: "LH-201",
                    value: $name,
                    problem: store.message(for: "name"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Field(
                    label: "Capacity",
                    placeholder: "60",
                    value: $capacity,
                    problem: store.message(for: "capacity"),
                    appearance: appearance
                )
                .onSubmit(commit)

                Text("Press return to save. Tessera will say if the engine refuses.")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }

            ContentSection("Where it is", appearance: appearance) {
                Chooser(
                    label: "Building",
                    options: store.buildings,
                    selection: $buildingID,
                    emptyHint: "No buildings yet — add one under Setup first.",
                    appearance: appearance
                )
                .onChange(of: buildingID) { commit() }

                MultiChooser(
                    label: "Features",
                    options: store.features,
                    selection: $featureIDs,
                    emptyHint: "No features yet — add them under Setup, then tick the ones this room has.",
                    appearance: appearance
                )
                .onChange(of: featureIDs) { commit() }

                if let problem = store.message(for: "building_id") ?? store.message(for: "feature_ids") {
                    Text(problem)
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.critical))
                }
            }

            AvailabilitySection(
                store: availability,
                subject: room.id,
                noun: "room",
                appearance: appearance
            )
        }
        // Keyed on the room's id, so selecting a different room refills the fields rather
        // than showing the previous one's values under the new one's name.
        .task(id: room.id) {
            name = room.name
            capacity = String(room.capacity)
            buildingID = room.buildingID
            featureIDs = room.featureIDs
        }
    }

    /// Send what is in the fields.
    ///
    /// A capacity that is not a number is sent as it is understood — zero — rather than
    /// silently corrected here, because the engine already refuses it with a sentence about
    /// capacity, and a second opinion in Swift would be a second validator to keep in step.
    private func commit() {
        var edited = room
        edited.name = name
        edited.capacity = Int(capacity) ?? 0
        edited.buildingID = buildingID
        edited.featureIDs = featureIDs
        // A relationship saves the moment it changes rather than on return: a menu and a
        // checkbox have no "commit" the way a text field does, and asking somebody to press
        // return after ticking a box is a rule they will not learn.
        Task { await store.save(edited) }
    }
}

/// When a room or an instructor cannot be used, drawn as the week itself.
///
/// Shared by both detail views (D5). It owns the term check and the empty case, so neither
/// screen has to repeat "availability belongs to a term" in its own words.
struct AvailabilitySection: View {
    let store: AvailabilityStore?
    let subject: Int
    let noun: String
    let appearance: Appearance

    var body: some View {
        ContentSection("When it cannot be used", showsRule: false, appearance: appearance) {
            if let store, let week = store.week {
                if let notice = store.notice {
                    Text(notice)
                        .font(Typography.caption.font)
                        .foregroundStyle(appearance.swiftUI(TextRole.critical))
                }
                AvailabilityGrid(
                    week: week,
                    blocked: store.blocked,
                    appearance: appearance,
                    block: { slots in Task { await store.block(slots) } },
                    free: { slots in Task { await store.free(slots) } }
                )
            } else if store == nil {
                Text("Availability belongs to a term. Choose one in the toolbar to set when "
                     + "this \(noun) is unavailable.")
                    .font(Typography.body.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.secondary))
            } else {
                Text("Loading the teaching week…")
                    .font(Typography.caption.font)
                    .foregroundStyle(appearance.swiftUI(TextRole.tertiary))
            }
        }
        // Keyed on the subject, so selecting another room fetches its slots rather than
        // showing the previous one's under the new one's name — the same mistake the
        // detail fields would make without their own key.
        .task(id: subject) { await store?.load(subject: subject) }
    }
}
