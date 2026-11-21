# Architecture decision records — index

All ADRs live in this directory, numbered in decision order. Each records the
decision, the alternatives, the consequences and the conditions that reopen it
(D2.2).

| ADR | Title | Status | Requirements |
| --- | --- | --- | --- |
| [001](001-material-claims.md) | Material claims in the final recommendation (incl. §4 fail-closed activation, §5 unconditional traceability) | Approved 2026-11-15; §4 activated 2026-11-17 | FR-005, QR-002, INV-005 |
| [002](002-analysis-profiles.md) | Three analysis profiles (quick / standard / deep) | Approved | FR-001 |
| [003](003-final-decision-validation.md) | Validate the final decision before it is adopted | Approved | FR-004, INV-001 |
| [004](004-token-budget.md) | Per-run token usage and optional-call budget (with the FR-008 reconciliation amendment) | Approved; amended 2026-11-19 | FR-002, FR-008 |
| [005](005-controlled-failures.md) | Controlled failure scenarios and a machine-readable failure record | Approved | QR-001 |
| [006](006-secret-redaction.md) | Secret redaction at output boundaries + PR-blocking secret scan | Approved | SEC-001 |
| [007](007-evaluation-protocol.md) | Paired evaluation and durable measurements | Approved | FR-007, PERF-001 |

Note for readers of historical records: ADR-002, ADR-004 and ADR-005 were
originally created at `docs/architecture/` and moved here during the final
documentation consolidation. Entries in `CHANGELOG.md` and
`docs/ai-use-log.yaml` that mention the old paths describe the state at the
time they were written and are intentionally not rewritten.
