# Internals

How Tessera works, subsystem by subsystem. Written for someone who needs to change the
code — including the author six months from now.

These documents explain **mechanism and reasoning**. For the *decisions* behind them
and the alternatives rejected, see [the ADRs](../adr/README.md); each internals
document links to the ADRs that constrain it.

| Document | Covers |
|---|---|
| [Project layout](project-layout.md) | Package structure, the architectural layers, and the tooling that enforces them |
| [Continuous integration](continuous-integration.md) | What runs on every push, and how to read a red build |
| [Domain model](domain-model.md) | The entities, the time grid, the group tree, and how migrations work |
| [API contract](api-contract.md) | The published surface, the error envelope, and the snapshot guard |
| [Structural data](structure-crud.md) | Rooms and their scaffolding — the repository pattern, filtering, and the deletion rules |
| [Student groups](student-groups.md) | The tree, cohorts, and the conflict relation the solver depends on |
| [Teaching](teaching.md) | Courses, terms, the frozen time grid, and how a weekly pattern expands into sessions |
| [Packaging and the sidecar](packaging.md) | How the engine and client become one `.dmg`, and how they find each other |

More arrive as the engine is built: the solver and the exporters.
