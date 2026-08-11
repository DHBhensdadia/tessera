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

More arrive as the engine is built: the domain model, the solver, the API contract, the
exporters.
