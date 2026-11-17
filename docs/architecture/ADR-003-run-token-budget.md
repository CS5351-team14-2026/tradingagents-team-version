# ADR-003 — Per-run token usage and optional-call budget

- Status: Accepted policy and interfaces (2026-11-18); S1–S3 implemented in the
  working tree, with stage verification recorded separately.
- Requirement authority: `docs/req/requirements.yaml`, REQ-TA-FR-002.
- Related requirements: REQ-TA-QR-001, REQ-TA-QR-003, REQ-TA-QR-004,
  REQ-TA-QR-005; preserve REQ-TA-INV-001/002/003/005/007.
- Human decision: "采用全部推荐方案，批准本计划及 **S1** 实施".
- Continuation decision: "继续实现s2和s3"; the historical S1 stage table below
  records the earlier authorization boundary.
- Approval evidence: `transcripts/FR-002-codex.md`.
- Supersedes: none. Extends the baseline; does not implement candidate FR-006.

The current S3 contract is appended at the end of this ADR. Earlier S1/S2
implementation-stage descriptions remain as historical design and gate
records; their future-tense statements do not revoke the continuation approval.

## Context and limits

The baseline counts tokens in `cli/stats_handler.py`. Its counters start at
zero and do not distinguish unavailable provider usage from actual zero.
The CLI passes callbacks to model construction and graph execution; direct
`TradingAgentsGraph.propagate()` users also need a shared accounting source.
Analysts and the Memory Log run in parallel. The graph starts the first Bull
and Aggressive contributions before it asks their continuation routers.
Structured-output retries, JSON-mode retries, free-text fallbacks and memory
reflections can each initiate further model calls.

FR-002 blocks **subsequent optional** calls after recorded usage reaches or
exceeds N. Requests already started can exceed N; concurrent requests already
admitted below N can collectively exceed it. This design neither cancels
issued requests nor claims a precise hard cap. `max_tokens` remains a
per-invocation output cap; round caps and SDK retry counts retain their own
meanings.

The candidate catalogue is background, not requirement authority. In
particular its phase-token-share experiment is a prerequisite for selecting a
final-report reserve percentage, which remains **TBD**.

## Approved policies D1–D10

| Decision | Accepted policy |
|---|---|
| D1 — partial usage | Count valid, non-overlapping reported token fields as a known lower bound. That lower bound reaching N is sufficient to block subsequent optional calls. Never label the partial sum a complete total. |
| D2 — unavailable usage | A completed call without usable usage makes the run's accounting incomplete. Conservatively block subsequent optional calls and report `BUDGET_WARNING` with an unavailable-usage reason unless known usage already establishes exhaustion. Do not estimate. |
| D3 — warning | Warning describes incomplete/conflicting/unverifiable observations, not a guessed numeric proximity to N. Recorded known usage at or above N takes precedence as `BUDGET_EXHAUSTED`. Complete recorded usage below N is `BUDGET_OK`. |
| D4 — calls and controlled degradation | Use the call-role table below. Required calls may continue beyond N. If valid inputs or a valid final result cannot be obtained, end through the controlled failure path with diagnostics and REVIEW, without inventing a recommendation. |
| D5 — parallelism and late events | Keep existing analyst/Memory Log parallelism. Admission and usage updates share a lock. A late event belongs to the run that started its call, never a later run. Do not serialize the graph to claim a hard cap. |
| D6 — input domain | Budget N is a non-negative integer, excluding booleans. Zero blocks optional calls immediately; `None` disables enforcement. Negative and non-integer inputs are invalid. Public configuration wiring is S3. |
| D7 — no budget | Preserve execution behaviour. The eventual budget result is `BUDGET_OK`, `NOT_CONFIGURED`, and `enforcement_enabled=false`; it does not certify that any numeric budget was enforced. Usage completeness is still reported honestly. |
| D8 — resume identity | Preserve a run's cumulative ledger, not a zero-initialized replacement. Budget value and policy version are part of budget-enabled resume identity. Persist events durably in S3; absent historical usage is an explicit `BUDGET_HISTORY_UNAVAILABLE` condition. |
| D9 — reflections | In-graph reflections count toward the current analysis that actually triggers them, including settlement of older decisions. Standalone/backtest-tail settlement has a separate context and record, not the last cell's remaining allowance. A skipped reflection stays pending. |
| D10 — SDK retries | Keep existing SDK retry configuration and treat its work as part of an already-started logical call. Do not claim admission control over every physical transport attempt or estimate usage for failed attempts. |

No numeric warning threshold, reserve ratio, or cost/performance target is
introduced by these decisions.

## Public module contracts

`src/tradingagents/run_budget.py` owns one run's ledger and pure budget policy.
It does not depend on CLI, graph internals, or provider SDKs. Its public
foundation consists of:

```python
UsageObservation(
    tokens_in=None, tokens_out=None, total_tokens=None,
    state="unavailable", source=None,
)
RunBudgetTracker(limit=None, run_id=None)
RunBudgetContext(tracker)
current_run_context()  # RunBudgetContext | None
```

An observation's state is `complete`, `partial`, `unavailable`, or `conflict`.
Counts are non-negative integers, never booleans. A genuine reported zero is
distinct from a missing field. A reported total and its input/output parts
are alternative views of the same usage, not additional amounts to sum.
For partial batch observations, the adapter can place the sum of disjoint
prompt lower bounds in `total_tokens` with the fixed source marker
`generations_lower_bound`. This is an adapter-computed lower bound of
provider-reported counts, not a raw provider exact total or an estimate.
The observation remains `partial`; it never supplies a complete displayed
run total. Exact provider assertions are preserved separately in the ledger
so a later callback can upgrade a bound without erasing a contradiction.

The tracker exposes these public operations:

```python
tracker.start_call(call_id, phase="unclassified")
tracker.finish_call(call_id, observation)
tracker.fail_call(call_id)
tracker.record_tool(call_id)
tracker.try_start(*, call_id, phase, role)  # StartDecision
tracker.snapshot()                       # immutable BudgetSnapshot
tracker.export_state()                   # versioned allowlisted data
RunBudgetTracker.restore(state)
context.activate()                      # context manager
```

`CallRole` has `OPTIONAL` and `REQUIRED` values. `StartDecision` contains
`allowed` and machine-readable `reason_codes`. `BudgetSnapshot.to_stats()`
adapts token/count/completeness observations for existing consumers; it does
not introduce the deferred S3 canonical budget-result block.

`start_call` is idempotent observation registration; it is not admission
control. `try_start` atomically admits an immediately dispatched logical call
or refuses an optional call. It must not issue permits that queue for later
dispatch. A lock protects call registration, usage replacement, tool counts,
budget decisions and snapshots; the network call does not run under that lock.

Callback identity deduplicates multiple deliveries of one event. A later,
more complete observation of the same call replaces its earlier observation
instead of incrementing usage twice. Conflicting metadata is labelled rather
than silently chosen or added. Refusal is a distinct control result; it must
not be handled as provider failure and trigger another fallback call.

`RunBudgetContext.activate()` binds the context for the current execution.
Callbacks retain the owner associated with the call's start identity, so an
end/error event delivered after context teardown cannot charge the next run.
Each analysis gets a fresh context except a validated resume of the same run.

`src/tradingagents/llm_clients/usage.py` owns provider observation adaptation:

```python
normalize_usage(response, *, provider=None)  # UsageObservation
UsageCallbackHandler(...)                  # LangChain callback adapter
```

The normalizer accepts supported standardized message usage and known
provider usage shapes; it handles the whole result rather than only the
first generation. Result-level totals are counted once, not once per
generation or in addition to message-level totals. Missing or invalid usage
stays unavailable/incomplete. It does not log or retain prompts, response
text, credentials or endpoint configuration.
Standardized `usage_metadata` wrappers also retain canonical semantics when
the caller supplies an Anthropic/Google provider hint; native wrappers keep
their provider-specific additive meanings.

Native field adaptation follows the semantics checked against the installed
LangChain adapters (Anthropic 1.7.10, Google GenAI 4.5.0 and OpenAI 1.8.0),
not an assumption that every provider's similarly named fields are identical:

- Anthropic raw input includes explicitly reported uncached input,
  cache-read input and cache-creation input. A complete cache-creation TTL
  breakdown is summed once and corroborates its aggregate when both exist;
  the breakdown and aggregate are never both added. Raw output already
  includes reasoning, so thinking is not added again.
- Google raw input combines reported prompt and tool-use prompt counts;
  output combines reported candidate and thought counts. Cached-content
  tokens are a subset, not another additive input amount. Supported raw
  fields include the corresponding camel-case and snake-case spellings.
- A missing additive field is never filled with zero. Uncertain canonical
  components remain null; an explicitly published exact total can remain as
  a partial observation. In an ambiguous native shape the adapter may retain
  less of the raw subcomponent lower bound rather than invent an exact value.
  Verified complete standardized usage takes precedence while known native
  exact fields/totals must corroborate it. Empty or partial OpenAI/generic raw
  usage cannot promote SDK-filled zeros into complete measurement.

Provider provenance uses only allowlisted provider identifiers/model-class
names per call, so mixed quick/deep providers are interpreted separately.
Unknown shapes remain unavailable/partial or conflicting as appropriate;
these adapter checks are not a promise of complete usage from every SDK or
transport attempt. SDK semantics changing requires re-evaluation and tests.

`cli.stats_handler.StatsCallbackHandler` adapts the same handler/ledger for
the existing CLI. It does not keep an independent token accumulator.
`TradingAgentsGraph.observation_scope()` yields the shared tracker and wraps
direct `propagate()` execution. The CLI activates
`RunBudgetContext(stats_handler.tracker)` around its existing execution path
and enters the graph's public observation scope when the graph exposes it;
legacy graph doubles use a no-op context instead. Both paths observe with
`limit=None` in S1. The graph's `run_settings()` reads an active snapshot only
while that graph owns its observation scope, so an unrelated graph's context
cannot replace its saved metadata. It retains the scope's usage after exit.
Consumers use the public snapshot; they do not inspect another module's
private counters or context variables.

S1 also separates settlement observation lifetimes. A reflection invoked
inside the graph reuses that graph's active ledger. Standalone
`settle_pending()` / `settle_all_pending()` execution, including the final
backtest settlement pass, activates a separate unbudgeted observation context.
Its callbacks cannot append usage to the last completed analysis through a
handler's fallback tracker. This uses an internal graph scope helper, not a
new public cross-module API. S1 provides this accounting isolation only;
durable standalone settlement records and budget-enabled backtest acceptance
remain S3 work.

## Call roles for S2 enforcement

| Call | Role and exhausted-budget behaviour |
|---|---|
| First invocation of each selected analyst | Required initial contribution. Missing valid input cannot be disguised as a completed analysis. |
| Analyst invocation after a tool round | Optional; check each new invocation before dispatch. Data tools themselves are not LLM usage. |
| Analyst report wrap-up | Required only for an analyst that has started and obtained context. It cannot manufacture a new mandatory analysis for an unstarted/empty analyst. Preserve INV-003 independently. |
| Sentiment or other structured retries/fallbacks | Optional; every attempt receives its own admission check. |
| Every Bull/Bear contribution, including first | Optional; guard both phase entry and each node, not just continuation routing. |
| Every Aggressive/Conservative/Neutral risk contribution, including first | Optional; guard phase entry and every subsequent invocation while retaining the existing risk routing map. |
| First Research Manager, Trader and Portfolio Manager invocation | Required synthesis/final path. Explicit skipped-phase markers must distinguish missing debate/risk work from normal completion. |
| Structured retry, PM JSON-mode retry and free-text fallback | Optional, even when the initial role invocation was required. Budget refusal never launches another fallback. |
| Every in-graph memory reflection | Optional; keep skipped entries pending and preserve settle-once, durable and nonblocking behaviour. |
| Standalone/backtest-tail settlement | Separate operation/context, not a continuation of the last analysis cell. |

If valid synthesis is impossible, the eventual controlled result is a
diagnostic report, existing lifecycle `failed`, and non-tradeable REVIEW.
Do not write a fabricated recommendation into the normal decision memory.
A valid result with optional work curtailed may retain lifecycle `completed`;
its budget result remains a separate dimension.

## Observation and record compatibility

The immutable snapshot exposes run identity, reported input/output counts, a complete total
only when available, known-token lower bound, usage state/completeness, call
and tool counts, pending calls, limit, budget status, machine-readable reasons
and refused calls. No observed token value is part of replayable settings.

S1 preserves canonical run-record schema and its lifecycle vocabulary:
`completed` / `failed`. Its `build_usage_summary` bridge must respect an
explicit `usage_complete=false` instead of inferring completeness from two
numeric partial aggregates. Missing usage is null and renders unavailable.
The CLI footer labels its counter `Tokens (observed)` and distinguishes
unavailable tokens from genuine reported zero. Its numeric values describe
only provider usage actually observed in the current invocation. A resumed
legacy checkpoint has unknown pre-checkpoint usage in S1:
retain the counts observed during the current invocation, but explicitly
mark the run incomplete and its full total null. The newly observed
remainder is not presented as the whole run. Durable historical accounting
remains S3 work.

S3 will add an allowlisted budget block under `run_metadata` and the budget
input under `replayable_settings`, retaining legacy flat fields and defining
the run-record schema migration. Expected reason distinctions include
`NOT_CONFIGURED`, `WITHIN_RECORDED_BUDGET`, `USAGE_PARTIAL`,
`USAGE_UNAVAILABLE`, `USAGE_CONFLICT`, `RECORDED_USAGE_REACHED_LIMIT` and
`RECORDED_USAGE_EXCEEDED_LIMIT`. This ADR does not change FR-006's candidate
status vocabulary or the evidence/rating acceptance rules.

## Recovery contract for S3

A graph-state snapshot alone cannot durably capture usage received between
checkpoint commits. S3 implements an idempotent event ledger through a public
checkpoint storage interface; state carries its identity and format version.
Only allowlisted accounting data is persisted, never prompts, response text,
credentials, endpoint URLs or local configuration paths.

Validated resume restores cumulative usage and deduplication identity. An
in-flight call whose result was lost in a crash is unknown, not zero. A legacy
checkpoint without a budget ledger must not be resumed as a budget-enabled
run with fabricated empty history; report `BUDGET_HISTORY_UNAVAILABLE` and
require an explicit new-run choice. No-budget execution preserves existing
historical signatures, resume lookup order and successful checkpoint cleanup.
Adding a default `None` setting must not alter historical signatures.

In-memory S1 export/restore is a serialization foundation, not a claim that
durable checkpoint recovery has already been implemented.

## Implementation stages and verification

| Stage | Scope | Human gate |
|---|---|---|
| S1 — approved for implementation | This ADR and interface registration; usage normalization; shared per-run ledger/context; observation-only CLI/graph wiring; foundation offline tests. Atomic admission is tested in isolation, not connected to graph dispatch. | Run whole-repo Ruff, full offline pytest, registry/schema, AI-use-log and diff checks; report results and stop. |
| S2 — not yet approved for implementation | Per-invocation admission, entry/continuation routing, controlled termination, reflection skipping and concurrency behavioural tests. | Separate approval before starting and after verification. |
| S3 — not yet approved for implementation | CLI/API budget configuration, budget metadata/reporting, durable resume ledger and backtest isolation acceptance. | Separate approval before starting; final acceptance afterwards. |

All deterministic tests belong in `test/offline/`, cite requirement/invariant
IDs, use existing network isolation and doubles, and preserve prior suites.
No new runtime dependency, live call, CI workflow change or prompt-policy
change is authorized by S1. The AI-use log records actual edits, actual human
decisions and actual test results; it cannot substitute planned work for
completed evidence.

## Phase-token-share experiment

First build an offline phase-measurement harness. A separately authorized
live/paid experiment then fixes provider, model, temperature, analysts,
vendors and ticker/date cases while recording provider-reported usage for
analyst, follow-up/tool, research, risk, final synthesis, retries and reflection.
Report phase-share distributions and missing-usage cases. The team chooses a
reserve only after reviewing that evidence. Until then final-report reserve
percentage and every quantitative calibration remain **TBD**.

## Re-evaluation triggers

- A provider's callback/usage semantics cannot be normalized without estimation.
- A required-call classification or fallback policy must change.
- More restrictive in-flight semantics would require graph serialization.
- Recovery cannot preserve the agreed identity and cumulative event history.
- A metadata consumer requires a different schema migration.
- The phase-token-share experiment supports a proposed reserve policy.

Any such scope or contract change returns to a revised plan and human approval.

## S2/S3 authorization and S2 invocation contract (2026-11-18)

After reviewing the S1 result, the human explicitly instructed:
"继续实现s2和s3". This approves implementation of the already accepted S2
and S3 scope; the historical stage table above records the earlier S1 gate.
Implementation remains staged, with whole-repository Ruff and full offline
pytest verification after each stage. This approval introduces no new budget
policy, threshold, live experiment, or FR-006 scope.

The previously approved invocation proposal is implemented through the public
`tradingagents.llm_clients.invocation` boundary:

```python
CallSpec(phase, role, call_id=...)  # str phase/identity, CallRole; UUID default
invoke_with_budget(model, model_input, *, context=None, call, config=None, **kwargs)
BudgetInvocationRefused  # exception with phase, reason_codes, call_id
```

The wrapper resolves an omitted context from `current_run_context()`, checks
admission immediately before dispatch, and preserves the logical call's
identity for callback normalization and direct-result observations. Refusal
means that no request was started; it never becomes a provider error that
launches a retry or fallback. Already admitted calls retain the approved
parallel and late-usage semantics, including possible recorded overspend.

Every `Reflector.reflect_on_final_decision()` invocation uses phase
`reflection` and role `OPTIONAL`. It uses the current run context, so in-graph
reflection belongs to the analysis that triggers it; the graph's existing
standalone settlement scope supplies a separate observation context.
`settlement.Settlement` retains `settled` and `failed` and adds
`budget_skipped: list[tuple[str, str, tuple[str, ...]]]`, defaulting to empty.
Each item identifies ticker, decision date and machine-readable refusal
reasons. A budget refusal leaves that decision and the remaining decisions
pending, stops the settlement pass, and stops an all-ticker pass before
another ticker attempts reflection. It does not populate provider `failed`
diagnostics. Outcomes already written remain durable; the existing
settlement lock, settle-once behaviour and `wait=False` behaviour are retained.

## S3 implemented contracts (2026-11-18)

### Configuration and run ownership

`config["token_budget"]` is the cumulative analysis allowance, accepting a
non-negative integer other than a boolean. `None` disables enforcement; zero
immediately refuses optional requests. The default is `None`.
`TRADINGAGENTS_TOKEN_BUDGET` supplies an integer environment default;
explicit CLI `--token-budget N` takes precedence. An explicit Python config
value controls Python callers. An active explicit `RunBudgetContext` can
supply the budget to the graph; a conflicting non-None graph limit is rejected
before dispatch. Output `max_tokens`, profile round settings and SDK retries
remain independent configuration.

`propagate()` and public `stream_run()` establish a run context when needed.
Public `begin_checkpoint()` / `stream_run()` / `end_checkpoint()` callers also
receive automatic observation scope management. Setup failures restore the
context and close checkpoint resources. Each begin must still be paired with
end in `finally`. An explicit invocation context is activated around the model
request and then restores the caller's enclosing context.

A fresh analysis receives a fresh ledger; validated resume preserves the
original identity and cumulative counts in the same referenced tracker. The
CLI handler, graph observer and per-invocation observer share this accounting
source. Constructor and invocation callbacks use a stable logical call ID,
so nested runnable events and duplicate deliveries do not create extra calls.
Already started requests remain concurrent and may collectively exceed N.

### Public durable storage boundary

```python
BudgetLedgerStore(data_dir, ticker, thread_id)
store.load()                 # allowlisted state or None; None means absent history
store.save_state(state)      # atomic committed update, or BudgetLedgerError
store.clear()                # retire this writer after clearing its owned revision
tracker.bind_persistence(writer)
tracker.restore_state(state)
tracker.recover_inflight()
tracker.mark_history_unavailable(reason_code="BUDGET_HISTORY_UNAVAILABLE")
tracker.raise_if_unhealthy()
```

The public store lives in `graph.checkpointer`; callers do not use its private
database path, connection or fields. A separate `budget_ledgers` table in the
existing per-ticker SQLite database persists the complete cumulative per-call
snapshot on every accounting event, independently of graph checkpoint commits.
The payload includes format version, run identity, limit, exhaustion, call
identities/phases/usage provenance, tool identities and refused calls. It
contains no prompts, response prose, credentials, endpoints or local paths.

Tracker admission and usage updates hold one lock through the atomic write.
A start is committed before its admission returns; model requests run outside
that lock. The store validates the accounting allowlist, uses revision and
generation compare-and-swap, and refuses competing resumed writers and stale
generations. Duplicate callbacks remain per-call updates. A retired writer
cannot recreate a completed run or overwrite the next generation. The store
retains the latest committed cumulative ledger; it is not a historical archive
of every revision.

`BudgetLedgerError` carries fixed `reason_code` / `reason_codes` and phase
`budget_ledger`, without storage exception text. A write failure latches the
tracker, including required dispatch, so a framework swallowing a callback
exception cannot make later invocation proceed. Memory settlement re-raises
this control error instead of treating it as a provider outage.

### Resume, replay and cleanup

Budget value and policy/state version enter the budget-enabled checkpoint
identity. A disabled default does not enter historical signatures; the
existing unbudgeted current/integration lookup order remains. Explicit
`clear_checkpoint(data_dir, ticker, date, signature)` removes graph rows and
the budget ledger for that same thread; clearing all checkpoints retains its
existing per-database scope.

Resume restores cumulative usage and deduplication identities before dispatch.
Started calls whose responses were lost are terminal `unavailable`, never
zero. Restored phases with any previously started call classify a newly replayed
request as an optional retry, even if that node's initial request was required.
An analyst's initial phase and its `.wrap_up` phase are distinct: an analyst
that acquired context can still make its first required wrap-up, while replay
of an already started wrap-up is optional. The original tool-round invariant
and graph route maps remain independently enforced.

An absent ledger for a resumable checkpoint, incompatible/malformed ledger,
ledger without matching graph history, or persistence failure cannot be
silently replaced with a fresh zero ledger. The graph returns a diagnostic
`failed` run with REVIEW, a machine-readable accounting reason and retained
available reports, without a normal memory recommendation. An explicit
checkpoint clear is the caller's fresh-run choice. A legacy unbudgeted resume
still marks both usage and budget usage completeness as partial/unavailable
when its pre-checkpoint usage is unknown.

After a valid synthesis the canonical terminal record is written before
retiring recovery history. If the budget store cannot be cleared, the valid
recommendation and lifecycle `completed` are preserved. The canonical record
adds the cleanup reason and `BUDGET_WARNING`, with already-established
`BUDGET_EXHAUSTED` taking precedence. Its recovery state is retained for an
explicit later cleanup; cleanup failure does not manufacture a replacement
recommendation or certify successful cleanup.

### Canonical metadata, reports and independent settlement

```python
build_run_record(..., budget: BudgetSnapshot | None = None)
build_budget_metadata(snapshot, *, usage=None)
```

Run-record schema `2` adds exactly the approved allowlisted budget block:

```text
run_metadata.budget = {
    limit, enforcement_enabled, status, reason_codes,
    known_tokens, usage_state, blocked_calls,
}
```

`replayable_settings.token_budget` appears only when enabled. Token counts and
budget results remain observations, separate from replay inputs. The existing
`completed` / `failed` lifecycle and legacy flat keys remain available. The
serializer preserves tracker status/reasons; with no configured enforcement
it records `BUDGET_OK`, `NOT_CONFIGURED`, and false enforcement. Unknown usage
stays null/unavailable; genuine reported zero remains distinguishable.
Schema-1 and legacy report settings still render without inventing a
historical budget claim.

Markdown and HTML show the same budget status, machine-readable reasons,
observed known-token lower bound, usage completeness and blocked-call count.
They explain that already started and required calls can exceed N; the result
does not claim a hard cap. A controlled failure renders REVIEW and `failed`,
and never enters normal decision memory. HTML treats diagnostics as escaped
text and retains the existing inert report behaviour.

In-graph reflection belongs to the triggering analysis. Standalone
`settle_pending()` / `settle_all_pending()`, including backtest-tail operations,
receive a separate context using the configured allowance and write their own
canonical settlement record. It cannot overwrite the last analysis's record
or charge its remaining allowance. Handled provider/price failures make that
operation's lifecycle `failed`; budget refusals remain separate
`budget_skipped` diagnostics and leave entries pending. A backtest cell has
its own analysis ledger, and controlled failed cells enter failures rather
than the successful-cell count.

S3 verification evidence is recorded only after checks run. No live/provider
or phase-token-share experiment has been performed as part of this contract.
Final-report reserve, numeric warning proximity thresholds and calibrated
cost/performance values remain **TBD**.
