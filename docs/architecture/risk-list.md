# Risk list

> Deliverable D2.10: assumptions that could become defects, each with the
> trigger that should force a review. Owner column is left for the team.

| # | Risk | Why it matters | Review trigger | Mitigation today |
| --- | --- | --- | --- | --- |
| R1 | Prompts live inline in code and change without a versioned diff | Behavioural drift invisible to review; the semantic-evaluation gate is unbuilt (DEBT-003) | Any edit under `src/tradingagents/agents/**`, `schemas.py`, `memory/reflection.py`, `date_window.py` | Versioned snapshots in `prompts/`; AI-use log entry per session; PR review |
| R2 | Claim audit depends on state keys produced by upstream agents | Renaming a report key would make every claim `UNKNOWN_SOURCE` and reject all runs | A run shows `DOWNGRADED` with `UNKNOWN_SOURCE` across all claims | Audit tests pin the vocabulary (`source_vocabulary`); runtime policy catalog documents the mapping |
| R3 | Budget relies on provider-reported usage | Providers that under-report or omit usage make the ceiling advisory | A provider change or a new provider is added | Usage recorded as unavailable (never estimated); `BUDGET_WARNING` honesty device; tests for missing/partial usage |
| R4 | Memory log grows without bound and stores prose verbatim | Disk growth; privacy exposure on a shared machine | More than ~1000 resolved entries, or sharing a machine | Optional rotation prunes only resolved entries; docs state the limitation (memory design §5–6) |
| R5 | Per-ticker SQLite checkpoints | Two concurrent runs of the same ticker can contend | Parallel runs of one ticker appear | Per-ticker database avoids cross-ticker contention; resume signature guard |
| R6 | All performance evidence came from one model family (`deepseek-flash`) | Numbers may not transfer to other providers | A different provider is used in the demo | Protocol records provider/model; ADR-007 reopen condition |
| R7 | The 8192-cap baseline qualification can be dropped when quoting numbers | Misleading “vs uncapped default” claim | Any report/demo quoting the reductions | Qualification recorded in the evidence README, registry fit criterion and review memo |
| R8 | Branch protection requires last-push approval and dismisses stale approvals | A push during a merge window invalidates the approval; merges stall | Any PR blocked right after an approval | Team practice: freeze `integration` during a merge window |
| R9 | Secret scan has detector blind spots and relies on a reviewed baseline | A real secret could be baselined as a false positive | Any `.secrets.baseline` change | `secret-baseline-approved` label + base-baseline comparison + entry-by-entry verification practice |
| R10 | Permission whitelist enforced by session config, not CI | An agent could write outside its whitelist | Any incident, or the first multi-agent session | DEBT-006 fitness function planned; PR review catches diffs |
| R11 | Some transcripts are annotated summaries rather than raw exports | D5 asks for complete raw records | Submission packaging | FR-001/FR-002-style annotated index + raw export where available; transcript naming normalised |
| R12 | Time: DDL 2026-11-23; `Report.md` not yet drafted | Report is a graded deliverable | Two days before DDL | Skeleton and evidence index ready in this consolidation; evidence bundles exist |
| R13 | `main` lags `integration` by a batch | The submission zip is cut from `main` | Before packaging | Batch PR to `main` opened and reviewed before the DDL |
