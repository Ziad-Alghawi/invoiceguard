# docs/decisions
Architecture Decision Records (ADR-NNN-title.md): every architectural choice and change of direction is written down here first.

New ADRs start from the [template](ADR-000-template.md).

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-001](ADR-001-stack.md) | Technology stack | Accepted |
| [ADR-002](ADR-002-code-vs-llm-boundary.md) | Boundary between deterministic code and LLMs | Accepted |
| [ADR-003](ADR-003-approval-hard-gate.md) | Human approval is a hard gate | Accepted |
| [ADR-004](ADR-004-model-router.md) | Model router with LiteLLM | Accepted |
| [ADR-005](ADR-005-zugferd-xrechnung-reader.md) | Reading ZUGFeRD and XRechnung with factur-x and an own lxml parser | Accepted |
| [ADR-006](ADR-006-demo-auth.md) | Demo authentication with seeded email/password users | Accepted |
| [ADR-007](ADR-007-background-execution.md) | Background execution with FastAPI BackgroundTasks and a status column | Accepted |
| [ADR-008](ADR-008-sync-database-access.md) | Synchronous SQLAlchemy 2 with psycopg 3 | Accepted |
| [ADR-009](ADR-009-kosit-validator-service.md) | KoSIT validator as its own service, called over HTTP | Accepted |
