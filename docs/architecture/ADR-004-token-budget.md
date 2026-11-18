# ADR-004 — Per-run token usage and optional-call budget

- Status: Accepted (2026-11-18). Interfaces and policies approved with the
  human decision "I approve, use your recommendation". Implementation is
  staged (S1 → S2 → S3) with a human gate after each stage.
- Requirement authority: `docs/req/requirements.yaml`, REQ-TA-FR-002.
- Related requirements preserved: REQ-TA-QR-001, QR-003, QR-004, QR-005;
  invariants REQ-TA-INV-002/003/005/007.
- Supersedes: none. Extends the v0.7.1 baseline (AGENTS.md §3). Does not
  implement FR-006 (candidate).
- Background only: the unmerged `feat/FR-002` branch (Codex) and its ADR-003
  informed this design; they are not an approved contract on this branch.

## Context and limits

The baseline counts tokens only in `src/cli/stats_handler.py`, wired from
`src/cli/run.py`. Counters start at zero and cannot distinguish "provider did
not report usage" from "zero tokens"; `TradingAgentsGraph.propagate()`
callers get no accounting at all. The graph starts the first Bull and
Aggressive contributions before it consults their continuation routers, and
analysts plus the Memory Log run in parallel. Structured retries, JSON-mode
retries, free-text fallbacks and reflections each initiate further model calls.

REQ-TA-FR-002 blocks **subsequent optional** calls once recorded usage reaches
or exceeds N. A single in-flight call may push recorded usage past N; this ADR
does not claim an exact hard cap. `max_tokens` remains a per-invocation output
cap; profile round counts and `llm_max_retries` are unrelated. The final-report
reserve percentage stays **TBD** until the phase-token-share experiment
(requirement-candidates.md §8) is recorded.

## Approved policies (from the approved plan D1–D6)

| ID | Decision |
|---|---|
| D1 partial usage | Count valid, non-overlapping reported token fields as a known lower bound. The lower bound reaching N is sufficient to block subsequent optional calls. Never present the partial sum as a complete run total. |
| D2 unavailable usage | A completed call without usable usage makes the run's accounting incomplete. Conservatively block subsequent optional calls and report `BUDGET_WARNING` with `USAGE_UNAVAILABLE` unless known usage already establishes exhaustion. Do not estimate or zero-fill. |
| D3 warning | `BUDGET_WARNING` describes incomplete/conflicting/unverifiable observations, not a guessed numeric proximity to N. Known usage at or above N is `BUDGET_EXHAUSTED`. Complete recorded usage strictly below N is `BUDGET_OK`. |
| D4 calls | Use the call-role table below. Required calls may continue beyond N; if a valid result cannot be produced the run ends through a controlled path with diagnostics and REVIEW, never a fabricated recommendation. |
| D5 concurrency | Keep analyst/Memory Log parallelism. Admission and usage updates share a lock. A late event belongs to the run that started its call. Do not serialize the graph to claim a hard cap; do not cancel issued calls. |
| D6 configuration | Budget N is a non-negative integer excluding booleans. Zero blocks optional calls immediately; `None` disables enforcement (baseline behaviour preserved). Negative/non-integer inputs are invalid. A budget value is part of the budget-enabled resume identity. |

No numeric warning threshold, reserve ratio, or cost/performance target is
introduced.

## Public module contracts

`src/tradingagents/run_budget.py` owns one run's ledger and pure budget policy.
It does not depend on CLI, graph internals, or provider SDKs.

```python
UsageObservation(tokens_in=None, tokens_out=None, state="unavailable")
    # state ∈ {"complete", "partial", "unavailable", "conflict"}
CallRole(StrEnum): OPTIONAL | REQUIRED
StartDecision(allowed: bool, reason_codes: tuple[str, ...])
BudgetSnapshot  # immutable: run_id, limit, tokens_in/out, total_tokens,
                # known_tokens, usage_complete, usage_state, llm_calls,
                # tool_calls, pending_calls, status, reason_codes
RunBudgetTracker(limit=None)
    start_call(call_id, *, role, phase)         # register in-flight
    finish_call(call_id, observation)           # idempotent replace, no double count
    fail_call(call_id)                          # unknown -> not zero
    record_tool(call_id)
    try_start(*, call_id, role, phase) -> StartDecision   # atomic admission
    snapshot() -> BudgetSnapshot
    to_usage_summary() -> UsageSummary bridge     # for run_record
RunBudgetContext(tracker)
    activate() -> context manager
current_run_context() -> RunBudgetContext | None
```

Reason codes (machine-readable, allowlisted): `NOT_CONFIGURED`,
`WITHIN_RECORDED_BUDGET`, `RECORDED_USAGE_REACHED_LIMIT`,
`RECORDED_USAGE_EXCEEDED_LIMIT`, `USAGE_PARTIAL`, `USAGE_UNAVAILABLE`,
`USAGE_CONFLICT`. Statuses: `BUDGET_OK`, `BUDGET_WARNING`, `BUDGET_EXHAUSTED`.

`src/tradingagents/llm_clients/usage.py` owns provider observation adaptation:

```python
normalize_usage(response, *, provider=None) -> UsageObservation
UsageCallbackHandler(tracker=None, *, provider=None)   # LangChain callback adapter
```

The normalizer reads standardized `usage_metadata` and known provider shapes
(Anthropic cache read/creation fields, Google prompt+tool-use / candidate+thought,
OpenAI Responses). It handles the whole result, counts a result-level total once,
never adds a subset into a total twice, and never fills a missing field with
zero. It does not retain prompts, response text, credentials, or endpoints.

`src/tradingagents/llm_clients/invocation.py` owns admission immediately before
a logical LLM invocation:

```python
CallSpec(phase, role, call_id=...)           # phase/identity strings; UUID default
invoke_with_budget(model, model_input, *, context=None, call, config=None, **kwargs)
BudgetInvocationRefused                      # NOT a provider error; never retried
```

A refusal means no request was started; callers translate it into a controlled
skip, never into a retry or fallback. Already-admitted calls and SDK transport
retries are not cancelled.

## Call roles

| Call | Role | Exhausted-budget behaviour |
|---|---|---|
| First invocation of each selected analyst | Required | runs (an unstarted analyst cannot be faked complete) |
| Analyst invocation after a tool round | Optional | checked before each new dispatch; remaining rounds skipped |
| Analyst report wrap-up | Required if the analyst already started | runs once; never manufactures analysis for an unstarted analyst |
| Structured retry / JSON-mode retry / free-text fallback | Optional | each attempt its own admission; refusal never launches another fallback |
| Every Bull/Bear contribution, including first | Optional | skipped with a `budget_skipped` phase marker; router goes to Research Manager |
| Every Aggressive/Conservative/Neutral contribution, including first | Optional | skipped marker; router goes to Portfolio Manager |
| First Research Manager / Trader / Portfolio Manager | Required synthesis/final | runs; if no valid result is possible → diagnostic + REVIEW + lifecycle `failed` |
| In-graph memory reflection | Optional | skipped; entry stays pending; settle-once preserved |
| Standalone / backtest-tail settlement | separate unbundgeted context | not charged to the last cell |

## Observation and record compatibility

`TradingAgentsGraph.observation_scope()` yields the shared tracker and wraps
direct `propagate()`/`stream_run()` execution, so API callers get enforcement,
not only the CLI. The CLI activates `RunBudgetContext(stats_handler.tracker)`.
`StatsCallbackHandler` adapts the same handler/ledger; it keeps no independent
token accumulator.

The canonical run record keeps schema version `1` and its lifecycle vocabulary
`completed` / `failed`. Budget information is a **separate** allowlisted
`run_metadata.budget` block (`status`, `limit`, `reason_codes`, `usage_state`,
`tokens_in`, `tokens_out`, `known_tokens`, `usage_complete`); it never changes
the lifecycle status. `token_budget` is recorded in `replayable_settings` (a run
input). Unavailable token values are null and render as "unavailable". A run
that completed with optional work curtailed keeps lifecycle `completed`; its
budget status is a separate dimension.

## Recovery contract

A no-budget run's checkpoint signature is byte-identical to the baseline:
adding a default `None` `token_budget` must not alter the signature (the
signature excludes it in the no-budget case). A budget-enabled run folds the
budget value into its identity so a resume cannot restore a mismatched budget.
A resumed run restores its cumulative ledger by identity; an in-flight call
whose result was lost in a crash is unknown, not zero. A legacy checkpoint
without a ledger is not resumed as budget-enabled with fabricated empty
history; it reports `USAGE_HISTORY_UNAVAILABLE`. Backtest cells each get a
fresh tracker; the backtest-tail settlement runs in a separate unbudgeted
context.

## Implementation stages and verification

| Stage | Scope | Gate |
|---|---|---|
| S1 | This ADR + trace; usage normalization; shared ledger/context/status model; observation-only CLI/graph wiring; foundation tests (normalization, status, config, metadata bridge). No routing/admission enforcement yet. | ruff check ., full offline pytest, registry/schema, AI-use-log, diff; report and stop |
| S2 | Per-invocation admission; entry/continuation routing; controlled termination; reflection skipping; concurrency behavioural tests. | ruff + full pytest; report and stop |
| S3 | CLI/API budget configuration; budget metadata/reporting; checkpoint resume ledger; backtest isolation; entrypoint tests; AI-use log entry. | ruff + full pytest; report and stop |

Implemented in this session on `feat/FR002-OpenCode` (all three stages above),
each verified with `ruff check .` and the full offline suite; the only failures
were the pre-existing Windows-GBK `read_text()` locale artifacts, reproduced on
the untouched baseline. The reserve percentage and every quantitative
calibration remain **TBD**.

All deterministic tests live under `test/offline/`, cite requirement/invariant
IDs, use the existing network isolation and doubles, and preserve prior suites.
No new runtime dependency, live call, CI workflow change, or prompt-policy
change is authorized here.

## Phase-token-share experiment (reserve %, TBD)

Build an offline phase-measurement harness that records provider-reported usage
per phase (analyst, follow-up/tool, research, risk, synthesis, retries,
reflection) over fixed ticker/date cases. A separately authorized live/paid run
then fixes provider, model, temperature, vendors and cases. The team chooses a
final-report reserve only from that evidence. Until then every quantitative
calibration, including the reserve percentage, remains **TBD**.

## Re-evaluation triggers

- A provider's callback/usage semantics cannot be normalized without estimation.
- A required-call classification or fallback policy must change.
- More restrictive in-flight semantics would require graph serialization.
- Recovery cannot preserve identity and cumulative history.
- A metadata consumer requires a different schema migration.
- The phase-token-share experiment supports a proposed reserve policy.
