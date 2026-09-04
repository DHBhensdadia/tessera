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
| [Constraints](constraints.md) | The rules that are stored rather than true, the registry that makes a new one cheap, and where the weight sliders write |
| [Importing a spreadsheet](import.md) | The two-step import, why pandas is fenced off from interpreting anything, and what "no partial write" means |
| [The browser console](console.md) | The HTML UI, how a browser gets past the engine token, and why it calls the repository directly |
| [Packaging and the sidecar](packaging.md) | How the engine and client become one `.dmg`, and how they find each other |
| [Solve jobs](solve-jobs.md) | Reading a term out of a project, running the solve as a job, and what a person watching is told |
| [Solving](solving.md) | How a term becomes a timetable and then a good one — the model, the objective, the outer search, and the one rulebook read twice |
| [Benchmarking](benchmarking.md) | How the solver is measured against numbers it did not choose — CB-CTT's objective, the second reading that checks it, the budget policy, and what the table does not claim |

More arrive as the engine is built: the exporters.
