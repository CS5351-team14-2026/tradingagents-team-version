# Memory / state design

> Deliverable D2.5. What state survives sessions, interruptions and versions;
> how it is written and retrieved; who owns it; how long it is kept; what the
> privacy posture is. Derived from the code paths named below.

## 1. State inventory

| State | Where it lives | Survives | Owner |
| --- | --- | --- | --- |
| Analysis memory log (decisions, outcomes, reflections) | `memory_log_path`, default `~/.tradingagents/memory/trading_memory.md` (env `TRADINGAGENTS_MEMORY_LOG_PATH`) | every session; append-only across versions | the machine user |
| Checkpoints (graph state for resume) | `data_cache_dir/checkpoints/<TICKER>.db` (SQLite, per ticker) | crashes and restarts *within* a run signature; invalidated when the signature changes | the machine user |
| Run record (settings, status, failure, budget, claim audit/acceptance) | `results_dir/<ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json` | per run, durable | the machine user |
| Reports (markdown tree + HTML) | `results_dir/<ticker>/…` | per run, durable; re-rendering replaces owned files | the machine user |
| Budget ledger (cumulative usage, blocked calls) | run state + checkpoint events (`run_budget.py`, `evaluation_checkpoint.py`) | run lifetime; restored with the checkpoint | the machine user |
| Evidence bundles (evaluation) | `docs/evidence/**` | committed to the repository | the team |

Nothing from a normal analysis run is committed to the repository; only the
evaluation evidence bundles are, and those contain no credentials (ADR-006,
ADR-007).

## 2. Write strategy

- **Memory log** — `store_decision` runs at the end of every completed run
  (`TradingAgentsGraph.record_decision`), idempotent per `(ticker, date)` under
  an exclusive file lock, written with a temp file + atomic rename. Pending
  entries are settled later by `memory/settlement.py`, which adds the outcome
  tag, raw/alpha performance, holding days and a `resolved:<date>` marker, then
  stores a reflection. Settlement takes its own lock so two processes do not
  pay for the same reflection twice.
- **Checkpoints** — off by default (`checkpoint_enabled: False`). When enabled,
  the thread id is `sha256(ticker:date:run-signature)`; any graph-affecting
  configuration change (analysts, models, rounds, profile, portfolio) changes
  the signature and a resume starts fresh instead of replaying mismatched
  state. Resume feeds `None` to avoid duplicating state; the checkpoint is
  cleared after a successful run.
- **Budget ledger** — cumulative usage is persisted with the run and restored
  from the checkpoint events; restored events are deduplicated. Missing,
  corrupt or incompatible history produces a controlled failure — history is
  never silently reset to zero (ADR-004 recovery contract).
- **Run record** — written once per completed or controlled-failed run;
  additive allowlisted fields only (`run_settings`, `run_metadata`, failure
  block, budget block, `claim_audit`, `claim_acceptance`).

## 3. Retrieval strategy

- **Cross-run lessons** — `get_past_context(ticker, n_same=5, n_cross=3,
  as_of=…)` returns recent same-ticker and cross-ticker reflections and is
  injected into the portfolio-manager context. Historical runs filter to
  entries whose `resolved:` date is on or before the analysis date, preventing
  look-ahead (INV-002).
- **Resume** — only matching source/configuration resumes; the run signature
  is the guard.
- **Evidence replay** — evaluation records carry the resolved allowlisted
  settings so a later run can replay the configuration (REQ-TA-FR-008); a
  whole-run token budget is explicitly *not* replayable (ADR-004 amendment).

## 4. Ownership and versioning

The repository owns the schema and the code paths; the machine user owns the
data files. Schema changes are additive and versioned (`BUDGET_STATE_VERSION`,
schema-versioned run records); readers tolerate older records. The memory log
format is stable across versions (`[date | ticker | rating | status]` +
`DECISION:` / `REFLECTION:` bodies, entries delimited by an HTML comment).

## 5. Retention

- Memory log: unlimited by default; optional rotation
  (`memory_log_max_entries`) prunes only the oldest **resolved** entries —
  pending entries are never pruned. Pending entries that never settle remain
  until manually removed.
- Checkpoints: cleared on success; `--clear-checkpoints` removes the database
  and its WAL/SHM files.
- Run records and reports: kept under `results_dir`; deletion is manual.
- Evidence bundles: retained in the repository for the project's life (they
  are the graded evidence).

## 6. Privacy posture

The memory log and run records store decision prose, reflections and
diagnostics **verbatim**; there is no PII scrubbing and no export/delete API
beyond deleting the files. Secrets are the exception and are actively
protected: redaction at output boundaries plus a PR-blocking secret scan
(ADR-006, REQ-TA-SEC-001). Team practice: run data stays on the operator's
machine; only redacted evidence bundles and the AI-use log are committed.
Known limitation recorded in `docs/debt-register.md`: retention policy for the
memory log is opt-in and unbounded by default.
