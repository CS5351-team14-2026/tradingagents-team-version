# ADR-005 — Controlled failure scenarios and a machine-readable failure record

- Status: Accepted (2026-11-18). Approved with the human decision "I approve,
  use your recommendation" (D-A…D-F).
- Requirement authority: `docs/req/requirements.yaml`, REQ-TA-QR-001.
- Related preserved: REQ-TA-FR-002 (budget), REQ-TA-QR-004 (run record
  lifecycle), REQ-TA-INV-001 (REVIEW rating), REQ-TA-FR-006 (candidate — not
  implemented here).
- Supersedes: none. Extends the v0.7.1 baseline (AGENTS.md §3). Builds on
  ADR-004 (FR-002) without changing its logic.

## Context

REQ-TA-QR-001 requires five controlled failure scenarios to each end with a
defined status and a safe diagnostic and **zero uncaught exceptions**, one
offline test each. Today the five behave inconsistently:

- **provider timeout** — the data path degrades to a `DATA_UNAVAILABLE`
  sentinel; an LLM-layer timeout raises an exception that `_run_graph`
  re-raises, so `propagate()` lets it escape (an uncaught exception).
- **invalid agent JSON** — `structured.invoke_structured` retries then falls
  back to free text; a fully-failed path can still raise.
- **missing API key** — `create_tier_client(...).get_llm()` raises `ValueError`
  at graph construction, which the CLI does not catch.
- **stock data unavailable** — degrades to `NO_DATA_AVAILABLE` /
  `DATA_UNAVAILABLE` sentinels (handled at the data layer), but no run-level
  code is recorded.
- **token budget exhausted** — controlled by FR-002 (`BUDGET_*` status and
  reasons), but not surfaced through a single failure code.

There is **no uniform per-run failure record**. The registry has **not**
approved a new top-level status enum, and QR-004 fixes the lifecycle status to
`completed` / `failed`; a uniform `status` enum for these scenarios is out of
scope.

## Decision

### D-A — Controlled return, not an escaping exception

`propagate()` (and the `_run_graph` path) never lets a provider timeout or an
exhausted structured path escape as an uncaught exception. On such a failure it
records the failure and returns a controlled `(final_state, "REVIEW")`, so a
caller receives a non-tradeable result with a diagnostic instead of a traceback.
The failed run still writes its run record; checkpoint teardown is unchanged.

Only a **classified** failure (a timeout/transport or a parse error, per
`failure.classify_exception`) becomes a controlled result. Any other exception
stays unclassified and is re-raised unchanged, so a genuine bug remains visible
and the existing checkpoint-resume test (which interrupts with a generic
`RuntimeError`) keeps its meaning: a crash is resumed, not masked. This refines
the earlier "the exception is re-raised" reason for the two D-A tests — they
were not changed, because they exercise the unclassified path, not timeout.

### D-B — Missing API key at construction

A missing/invalid provider key surfaces at graph construction, before any run or
run-record writer exists. `TradingAgentsGraph.__init__` raises a typed
`MissingApiKeyError` (carrying only the env-var name, never the key value); the
CLI `run_analysis` catches it at construction, prints a safe diagnostic, and
writes a standalone run record with `status=failed`,
`failure.code=MISSING_API_KEY`, `exception_type`, and `final_rating=REVIEW`.
Programmatic callers see the typed error (a `ValueError` subclass), which is a
defined, catchable contract rather than an opaque failure.

### D-C — `run_metadata.failure` shape

Additive, allowlisted block, present only on a controlled failure:

```
run_metadata.status: "completed" | "failed"        # unchanged vocabulary (QR-004)
run_metadata.failure:
  code: PROVIDER_TIMEOUT | INVALID_AGENT_JSON | MISSING_API_KEY
        | STOCK_DATA_UNAVAILABLE | TOKEN_BUDGET_EXHAUSTED
  phase: <machine-readable phase string>
  diagnostic: <fixed safe human-readable text>
  exception_type: <optional non-sensitive class name>
final_rating: "REVIEW"
run_metadata.budget.status: BUDGET_OK | BUDGET_WARNING | BUDGET_EXHAUSTED  # unchanged
```

No new field is invented beyond this set.

### D-D — Lifecycle status for graceful degradation

A run that degrades but still produces a valid report keeps `status=completed`
and records `failure.code` (e.g. `STOCK_DATA_UNAVAILABLE` when data was absent
but a caveated report was produced). `status=failed` is used only when no valid
output could be produced (e.g. missing API key, unrecoverable provider timeout).
`final_rating=REVIEW` is recorded whenever no valid tradeable conclusion exists
(REQ-TA-INV-001, reused — not re-invented).

### D-E — Safe diagnostics

`diagnostic` is a **fixed** message per code. `exception_type` is an optional
class name only. Neither the raw exception text, HTTP URLs, endpoints, keys,
nor local paths are ever recorded. This satisfies REQ-TA-SEC-001 / INV-006
intent without touching the secret-scrubbing path.

### D-F — New ADR

This ADR-005 is separate from ADR-004 so FR-002's contract stays stable and the
QR-001 decision has its own record.

### D-G — No registry change

REQ-TA-QR-001's statement, priority and status are unchanged; only the ADR and
the trace record are added. No schema-gate churn.

## Module

`src/tradingagents/failure.py` owns the closed `FailureCode` vocabulary and two
pure helpers:

```python
FailureCode(StrEnum): PROVIDER_TIMEOUT | INVALID_AGENT_JSON | MISSING_API_KEY
                      | STOCK_DATA_UNAVAILABLE | TOKEN_BUDGET_EXHAUSTED
build_failure(code, *, phase, exception_type=None) -> dict   # {code, phase, diagnostic, exception_type?}
classify_exception(exc) -> FailureCode | None                # maps a provider/JSON error to a code
FailureRecord / failure_block(...)                           # allowlisted run_metadata.failure
```

It depends only on the standard library and the public error taxonomy
(`dataflows/errors.py`), not on the graph, CLI, or provider SDKs (SC-1).

## Record and report compatibility

`run_record.build_run_record` accepts an optional `failure` mapping placed under
`run_metadata.failure` (allowlisted). The lifecycle `status` field is
unchanged. `reporting._header` and `report_html._run_details` render one
"Failure:" line (code + phase + diagnostic) additively.

## Consequences

- `propagate()` no longer raises on the five controlled scenarios; it returns a
  controlled `(state, REVIEW)` or the typed `MissingApiKeyError` at
  construction. Callers must guard with `is_review` (already documented).
- New tests: one per scenario, offline, test doubles, asserting status, failure
  code, safe diagnostic, no uncaught exception, and `final_rating=REVIEW`.
- FR-002 budget statuses are mirrored through `failure.code=TOKEN_BUDGET_EXHAUSTED`
  on the review path only; FR-002 logic (ADR-004) is untouched.

## Re-evaluation triggers

- A scenario's cause needs a new failure code (closed vocabulary changes).
- A required-call/degradation policy must change (FR-006 lands).
- A consumer needs a different record schema migration.
- A safety-critical file must change to type an error (needs its own ADR).

## Amendment (2026-11-19) — FR-008 compatibility

`run_metadata.failure` is **observational**, like `run_metadata.budget`: it is
never part of `replayable_settings`, so a failed (or completed) run's record
remains replayable by REQ-TA-FR-008, which reads only `schema_version` +
`replayable_settings`. `token_budget` is likewise observational
(`run_metadata.token_budget`), not replayable (see the ADR-004 amendment). The QR-004
lifecycle `completed`/`failed` vocabulary is unchanged. Pinned by
`test/offline/test_qr001_fr008_reconcile.py`.
