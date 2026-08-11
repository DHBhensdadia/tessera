# Architecture Decision Records

One file per significant decision: the context that forced it, what was decided, and
what it costs. Written when the decision is made, while the alternatives are still
fresh, so that a year later the reasoning can be read rather than reconstructed.

A decision that turns out wrong is superseded by a new record rather than edited — the
history of what was believed and why is the useful part.

| # | Decision |
|---|---|
| [0001](0001-engine-client-sidecar.md) | Python engine and SwiftUI client, joined by a loopback sidecar |
| [0002](0002-cpsat-fix-and-optimize.md) | CP-SAT driven by Fix-and-Optimize, not a pure metaheuristic |
| [0003](0003-framework-free-domain.md) | The domain layer imports no framework, enforced in CI |
| [0004](0004-one-validator.md) | One constraint validator, shared by the solver and the UI |
| [0005](0005-integer-slot-grid.md) | Time is an integer slot index, never a timestamp |
| [0006](0006-sqlalchemy-over-sqlmodel.md) | SQLAlchemy 2.0 rather than SQLModel |
| [0007](0007-pdf-in-python.md) | Generate PDFs in Python with ReportLab, not native PDFKit |
| [0008](0008-in-process-jobs.md) | Solve jobs run in-process; no Celery, no Redis |
| [0009](0009-custom-drag-gesture.md) | Custom DragGesture rather than draggable/dropDestination |
| [0010](0010-ship-unnotarized-first.md) | Ship unnotarized initially; add Developer ID later |
| [0011](0011-arm64-only.md) | Apple Silicon only; no Intel build |
| [0012](0012-viewport-scoped-validation.md) | Validation endpoints take an explicit viewport |
| [0013](0013-solver-formulation.md) | Model sessions as intervals, not a boolean placement cube |
| [0014](0014-slot-granularity.md) | 30-minute slots by default, configurable per project |
| [0015](0015-solo-git-workflow.md) | Direct commits to main; protection limited to force-push and deletion |
