import EngineClient
import Foundation

/// The four sets of operations, and the only place the generated names appear for them.
///
/// Each is four calls. Written out rather than derived, because the engine's routes are not
/// uniform enough to derive from — `student-groups` is not `programs` with a different noun
/// — and a clever generic that fits three of four is worse than four honest declarations.
extension SimpleEntityStore.Operations {
    static let buildings = Self(
        list: { connection in
            try await connection.run { try await $0.listBuildings().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        },
        create: { connection, name, institution in
            let made = try await connection.run {
                try await $0.createBuilding(
                    body: .json(.init(institution_id: institution, name: name))
                ).created.body.json
            }
            return .init(id: made.id, name: made.name)
        },
        rename: { connection, item in
            var changes = Components.Schemas.BuildingUpdate()
            changes.name = item.name
            _ = try await connection.run {
                try await $0.updateBuilding(path: .init(building_id: item.id), body: .json(changes)).ok
            }
        },
        remove: { connection, id in
            _ = try await connection.run { try await $0.deleteBuilding(path: .init(building_id: id)) }
        }
    )

    static let features = Self(
        list: { connection in
            try await connection.run { try await $0.listFeatures().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        },
        create: { connection, name, institution in
            let made = try await connection.run {
                try await $0.createFeature(
                    body: .json(.init(institution_id: institution, name: name))
                ).created.body.json
            }
            return .init(id: made.id, name: made.name)
        },
        rename: { connection, item in
            var changes = Components.Schemas.FeatureUpdate()
            changes.name = item.name
            _ = try await connection.run {
                try await $0.updateFeature(path: .init(feature_id: item.id), body: .json(changes)).ok
            }
        },
        remove: { connection, id in
            _ = try await connection.run { try await $0.deleteFeature(path: .init(feature_id: id)) }
        }
    )

    static let departments = Self(
        list: { connection in
            try await connection.run { try await $0.listDepartments().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        },
        create: { connection, name, institution in
            let made = try await connection.run {
                try await $0.createDepartment(
                    body: .json(.init(institution_id: institution, name: name))
                ).created.body.json
            }
            return .init(id: made.id, name: made.name)
        },
        rename: { connection, item in
            var changes = Components.Schemas.DepartmentUpdate()
            changes.name = item.name
            _ = try await connection.run {
                try await $0.updateDepartment(path: .init(department_id: item.id), body: .json(changes)).ok
            }
        },
        remove: { connection, id in
            _ = try await connection.run { try await $0.deleteDepartment(path: .init(department_id: id)) }
        }
    )

    static let programs = Self(
        list: { connection in
            try await connection.run { try await $0.listPrograms().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        },
        create: { connection, name, _ in
            let made = try await connection.run {
                try await $0.createProgram(body: .json(.init(name: name))).created.body.json
            }
            return .init(id: made.id, name: made.name)
        },
        rename: { connection, item in
            var changes = Components.Schemas.ProgramUpdate()
            changes.name = item.name
            _ = try await connection.run {
                try await $0.updateProgram(path: .init(program_id: item.id), body: .json(changes)).ok
            }
        },
        remove: { connection, id in
            _ = try await connection.run { try await $0.deleteProgram(path: .init(program_id: id)) }
        }
    )

    /// The university itself.
    ///
    /// A file usually holds one, made by the creation sheet — but the console has always
    /// listed them, a name typed into that sheet is otherwise uncorrectable, and #25 says a
    /// project is a real file people pass around, so a second institution in one file is a
    /// thing the engine allows and the interface should not pretend away.
    ///
    /// The only entity here whose `create` ignores the institution it is handed, for the
    /// obvious reason.
    static let institutions = Self(
        list: { connection in
            try await connection.run { try await $0.listInstitutions().ok.body.json }
                .items.map { .init(id: $0.id, name: $0.name) }
        },
        create: { connection, name, _ in
            let made = try await connection.run {
                try await $0.createInstitution(body: .json(.init(name: name))).created.body.json
            }
            return .init(id: made.id, name: made.name)
        },
        rename: { connection, item in
            var changes = Components.Schemas.InstitutionUpdate()
            changes.name = item.name
            _ = try await connection.run {
                try await $0.updateInstitution(
                    path: .init(institution_id: item.id), body: .json(changes)
                ).ok
            }
        },
        remove: { connection, id in
            _ = try await connection.run {
                try await $0.deleteInstitution(path: .init(institution_id: id))
            }
        }
    )
}
