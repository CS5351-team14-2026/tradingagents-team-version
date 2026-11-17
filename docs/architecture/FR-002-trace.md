# REQ-TA-FR-002 — staged traceability record

- Authority: `docs/req/requirements.yaml`, REQ-TA-FR-002 (must, implement).
- Contract: `ADR-003-run-token-budget.md`, accepted on 2026-11-18.
- Starting HEAD: `889cc33cf60bc89573159438ff98191e17adba77`.
- Approval evidence: `transcripts/FR-002-codex.md`.
- Stage authorization: S1 approved first; the subsequent human instruction
  "继续实现s2和s3" authorizes S2 and S3.
- Current implementation: S1–S3 are present in the working tree. Stage check
  results are recorded separately; implementation is not a claim of a live
  provider experiment or a precise hard cap.

S1 established accounting and observation foundations; S2 connected invocation
admission and controlled routing/termination; S3 connects public configuration,
durable cumulative recovery, canonical metadata/reporting and backtest
isolation. Historical S1/S2 records below retain their original scope and
evidence. The S3 mapping at the end identifies current files and actual test
names; passing results are recorded only after the checks run.

## Requirement fit criteria

| Criterion | Component and stage | Offline evidence |
|---|---|---|
| Accept maximum per-analysis N | S1 `run_budget.RunBudgetTracker` validates non-negative integer/None; S3 `default_config.py`, CLI and graph configuration wire the public input | `test_token_budget.py` input validation/zero/None; `test_budget_configuration.py::test_req_fr002_environment_budget_is_nonnegative_integer`, `::test_req_fr002_real_cli_config_flag_wins_over_environment`, `::test_req_fr002_graph_rejects_invalid_budget_before_provider_or_files` |
| Recorded usage >= N prevents every subsequent optional call | S1 atomic `try_start`; S2 per-invocation dispatch and graph entry/continuation guards, including first Bull/Aggressive calls; S3 recovered-phase replay is optional | `test_budget_calls.py::test_req_fr002_each_analyst_tool_followup_is_optional`; `test_budget_graph_routing.py::test_fr002_every_research_and_risk_call_is_blocked_after_recorded_limit`; `test_budget_memory.py::test_fr002_reflection_is_optional_after_recorded_limit`; `test_budget_ledger_store.py::test_fr002_replayed_required_phase_is_an_optional_retry_after_resume` |
| Status in BUDGET_OK/WARNING/EXHAUSTED plus machine-readable reason | S1 snapshot/pure policy; S3 canonical schema-2 budget metadata and both report renderers | `test_budget_reporting.py::test_fr002_budget_results_and_reasons_are_machine_readable_without_changing_status`, `::test_fr002_markdown_and_html_report_same_observed_budget_and_unknown_usage` |
| Started requests may exceed N; no precise hard cap | S1 ledger accepts reported excess; S2 preserves existing parallel analysts; reports explain the boundary | `test_budget_concurrency.py::test_fr002_parallel_admitted_calls_can_collectively_overshoot_then_block_new_calls`, `::test_fr002_budget_keeps_parallel_initial_analysts`; `test_budget_reporting.py` |
| Missing provider usage is unavailable, never estimated | S1 `llm_clients.usage`, shared callback, `run_budget`, CLI adapter and `run_record.build_usage_summary` | S1 `test_budget_usage.py` and `test_token_budget.py`: complete/partial/missing/conflicting/zero usage, aggregate vs message usage, callback deduplication; `test_budget_entrypoints.py::test_fr002_partial_or_missing_usage_is_never_a_complete_zero` and `::test_fr002_cli_distinguishes_unavailable_usage_from_reported_zero` |
| Final-report reserve remains TBD until experiment | ADR-003; no reserve constant introduced in S1/S2/S3 without the experiment and further decision | Human diff review; separately approved phase-token-share measurement, not an offline estimate |

## Related requirements and invariants

| ID | S1 scope and retained contract | Evidence / later work |
|---|---|---|
| REQ-TA-QR-001 | Foundation error/usage states are controlled; production budget-exhaustion termination is S2 | S2 controlled exhaustion/no-fallback tests planned. Map existing timeout/invalid-JSON/missing-key/data-unavailable tests separately; do not claim all five scenarios implemented by S1 |
| REQ-TA-QR-003 | Accounting is a public shared module; provider adaptation and CLI display use public interfaces and replaceable doubles | `test_layering.py`, whole-repo `ruff check .`, full offline `pytest -q` |
| REQ-TA-QR-004 | Respect explicit incomplete usage; keep null unavailable total and existing `completed`/`failed` lifecycle/schema in S1 | `test_run_record.py`, S1 usage/integration tests; S3 independent budget metadata and schema migration |
| REQ-TA-QR-005 | New deterministic tests live under `test/offline/`, using existing network isolation and temporary state | `conftest.py`, `test_suite_isolation.py`, full offline suite; isolated/random-order acceptance is S3 |
| REQ-TA-INV-001 | Observation changes cannot turn a missing/invalid rating into a tradeable decision | `test_rating_integrity.py`, `test_signal_processing.py`; S2 exhausted-no-result REVIEW test planned |
| REQ-TA-INV-002 | Preserve point-in-time data/tool/memory behaviour | Existing date-boundary, tool-date and memory-point-in-time tests |
| REQ-TA-INV-003 | No S1 graph routing change; original tool cap/wrap-up remains independent | `test_graph_end_to_end.py` tool-cap/wrap-up tests; S2 joint budget/tool-cap regression planned |
| REQ-TA-INV-005 | Observation does not bypass claim audit/acceptance | Existing material-claim and claim-acceptance tests; S2 partial/diagnostic result regression planned |
| REQ-TA-INV-007 | Preserve deterministic pre-agent instrument resolution | Existing instrument-identity, symbol and normalization tests |

## S1 data flow and ownership

1. Direct graph/API execution uses `TradingAgentsGraph.observation_scope()`;
   the CLI activates `RunBudgetContext(stats_handler.tracker)` for its existing
   run path and also enters the graph observation scope when exposed. Legacy
   graph doubles use a no-op context. Both observe with `limit=None` in S1.
2. Model callbacks register logical calls and normalize reported provider usage.
3. Duplicate deliveries share a call identity and one per-run ledger.
4. Public snapshots supply CLI observations and QR-004 usage metadata.
5. Scope teardown retains call ownership for late callbacks; later runs get a
   separate context. S3 supplies durable resumed identity.

The graph reads current observations only during its own scope. Unrelated
active contexts cannot overwrite another graph's saved metadata. A legacy
checkpoint resume keeps this invocation's known observations but marks full
run usage incomplete/null because the historical portion is not yet restored.
This is honest observation in S1, not S3 durable accounting.
The CLI footer explicitly labels its counter `Tokens (observed)`: a number
there is current-invocation measured usage, not a resumed full-run total.
The canonical resumed run metadata remains incomplete with a null full total.
In-graph reflections share the graph's active ledger. Standalone
`settle_pending()` and `settle_all_pending()` operations use a separate
unbudgeted observation context, including a backtest's final settlement pass,
so callback fallback cannot charge the last analysis. This S1 isolation does
not claim durable standalone settlement records or complete budget-enabled
backtest acceptance; both remain S3.

Partial batch sums use the adapter marker `generations_lower_bound`; they
remain partial lower bounds, never a purported exact provider total. A later
complete callback upgrades the original call once while preserving exact
provider assertions needed for conflict detection.

Native provider adaptation follows the verified installed adapter semantics:
Anthropic cache-read/cache-creation inputs are additive to uncached input,
cache-creation TTL details corroborate rather than duplicate the aggregate,
and Google thought/tool-use prompt tokens contribute to their respective
output/input components while cached-content tokens remain a subset.
Missing additive fields never become zero; uncertain components stay null,
published exact totals can remain partial, and contradictory exact fields
remain conflict. Unknown/provider-specific shapes do not acquire fabricated
complete totals. See ADR-003 for the supported field boundary and inspected
SDK versions; no full-provider-coverage claim is made by these observations.

`run_budget` owns accounting and policy; `llm_clients.usage` owns response
adaptation; the graph owns execution lifecycle; CLI owns presentation; the
existing canonical run record owns persisted observation formatting. There
is no independent CLI token accumulator and no private cross-component read.

## S1 entrypoint and compatibility evidence

All tests listed here are in `test/offline/test_budget_entrypoints.py` and
exercise the observation-only wiring with the existing scripted graph and
CLI doubles. The final S1 full-suite run passed; see the verification record below.

| Behaviour | Exact test |
|---|---|
| Direct graph call accounting and duplicate callbacks | `test_fr002_direct_graph_observes_all_calls_without_double_counting` |
| Partial/missing provider usage is incomplete, not zero | `test_fr002_partial_or_missing_usage_is_never_a_complete_zero` |
| Reused graph starts a fresh analysis ledger | `test_fr002_reused_graph_starts_a_fresh_observational_ledger` |
| Both standalone settlement operations cannot charge the preceding analysis | `test_fr002_standalone_settlement_cannot_charge_the_last_analysis` (parameterized over `settle_pending` / `settle_all_pending`) |
| Provider failure still records observations and retains existing failure behaviour | `test_fr002_failure_records_observed_usage_and_preserves_failure_contract` |
| Real CLI and graph use one accounting source | `test_fr002_real_cli_and_graph_share_one_observational_ledger` |
| Scope restores an enclosing context | `test_fr002_observation_scope_restores_an_enclosing_context` |
| Explicit QR-004 incomplete flag survives numeric component counts | `test_fr002_qr004_explicit_incomplete_usage_cannot_be_reclassified` |
| Unrelated graph context cannot pollute saved metadata | `test_fr002_another_graph_context_cannot_replace_saved_run_metadata` |
| Resumed unknown history cannot become a complete zero/remainder | `test_fr002_resumed_history_is_not_replaced_by_a_complete_zero_or_remainder` |
| Nullable CLI footer and genuine zero remain distinguishable | `test_fr002_cli_distinguishes_unavailable_usage_from_reported_zero` |

## Verification record

S2 final verification (2026-11-18): whole-repository Ruff passed; full offline
selection passed **1829 tests, 6 skipped, 1 deselected, 24 warnings and
100 subtests in 49.27s**. Registry/schema validation passed. The new call,
routing, concurrency, invocation, memory and termination tests cover the S2
boundary; S3 configuration/reporting/recovery acceptance is still pending.
The human's explicit instruction "继续实现s2和s3" authorizes proceeding to S3
after recording S2 checks; no additional scope is implied.

On 2026-11-18 the final S1 code passed whole-repo `ruff check .` and full
`pytest -q`: **1753 passed, 6 skipped, 1 deselected, 24 warnings, 100 subtests
passed in 47.95s**. The suite used the repository's configured test directories
and `not integration` selection, an isolated temporary working directory and
environment, disabled dotenv discovery in a temporary runner, and Python
UTF-8 mode. No repository test fixture was changed for that isolation.
Five skips concern Windows/POSIX compatibility; one concerns the uninstalled
optional `langchain_aws` package. No live/provider experiment was run.

The registry and registry-template passed `validate_req_registry.py` against
`req-schema.json` using the existing system Python. No dependency was installed
or configuration changed; other available interpreters lacked `jsonschema`.
The AI-use-log validator passed with 13 well-formed entries and
`git diff --check` passed. New-file whitespace is checked separately before
stage close. Earlier failed validation attempts
and the test corrections are documented in the session record and AI-use log.

These results verify S1 only. At that historical gate S2 and S3 remained
unimplemented and required further approval under `Prompt.md` Step 4; the
subsequent continuation authorization is recorded next.

## S2/S3 continuation authorization (2026-11-18)

The human's subsequent instruction, "继续实现s2和s3", explicitly authorizes
the previously approved S2 and S3 scope. The S1-only statements above describe
the earlier gate and its verified evidence. Each stage retains the required
Ruff/full-offline-suite verification; no later-stage verification result is
implied by authorization alone.

S2 uses the approved `invoke_with_budget` public boundary, `CallSpec` role
and phase classification, and a distinct `BudgetInvocationRefused` control
result. Every memory reflection is optional. Settlement records budget
refusals separately in additive `Settlement.budget_skipped` machine-readable
diagnostics, leaves skipped entries pending and stops before attempting the
remaining entries or tickers. It preserves outcomes already written and the
existing log locking/nonblocking behaviour.

| Requirement / invariant | S2 memory behaviour | Offline acceptance tests in `test_budget_memory.py` |
|---|---|---|
| REQ-TA-FR-002 | Reflection does not start at or above N; an admitted request can exceed N | `test_fr002_reflection_is_optional_after_recorded_limit`; `test_fr002_started_reflection_can_exceed_limit_and_blocks_the_next_one` |
| REQ-TA-FR-002, REQ-TA-QR-004 | Partial/missing usage stays incomplete and conservatively blocks later optional reflections | `test_fr002_incomplete_reflection_usage_is_not_a_complete_zero` |
| REQ-TA-FR-002, REQ-TA-QR-001 | Budget refusal is controlled, distinct from provider failure, and stops remaining/ticker reflection attempts | `test_fr002_budget_refusal_leaves_pending_without_attempting_remaining_reflections` |
| REQ-TA-FR-002, REQ-TA-INV-002 | Finished lessons remain durable and skipped entries can settle once in a later operation | `test_fr002_settlement_keeps_finished_outcomes_when_later_reflection_is_refused` |
| REQ-TA-FR-002, REQ-TA-QR-001/005 | No-budget provider failures remain nonblocking; budget does not bypass the settlement lock | `test_fr002_no_budget_keeps_provider_failure_nonblocking_and_pending`; `test_fr002_budgeted_settlement_still_honours_nonblocking_log_lock` |

These test names identify the S2 acceptance coverage. Actual check results
must be recorded after verification; no live/provider experiment is included.

## S3 implementation steps and test mapping

All test paths in this section are under `test/offline/`. These mappings
describe implemented acceptance coverage, with existing network isolation,
scripted model doubles and temporary files. They do not substitute for the
stage verification record.

| Step / approved behaviour | Production files | Exact offline acceptance coverage |
|---|---|---|
| S3.1 — expose None/zero/non-negative cumulative budget; environment default and explicit CLI precedence; reject invalid values before providers/files | `default_config.py`, `cli/main.py`, `cli/run.py`, `graph/trading_graph.py` | `test_budget_configuration.py::test_req_fr002_budget_disabled_by_default`; `::test_req_fr002_environment_budget_is_nonnegative_integer`; `::test_req_fr002_invalid_environment_budget_is_rejected`; `::test_req_fr002_cli_explicit_budget_reaches_run_separately_from_flags`; `::test_req_fr002_real_cli_config_flag_wins_over_environment`; `::test_req_fr002_graph_rejects_invalid_budget_before_provider_or_files` |
| S3.2 — persist every accounting event independently of graph commits; deduplicate restored calls and reject malformed history | `run_budget.py`, `graph/checkpointer.py` | `test_budget_ledger_store.py::test_fr002_ledger_commits_every_start_usage_failure_tool_and_refusal`; `::test_fr002_duplicate_and_richer_callbacks_remain_idempotent_after_durable_resume`; `::test_fr002_corrupt_durable_history_is_reported_without_resetting_it`; `test_budget_checkpoint.py::test_fr002_usage_committed_without_graph_checkpoint_is_never_silently_zeroed` |
| S3.3 — revision/generation compare-and-swap, rollback and stale-writer retirement preserve concurrent accounting | `graph/checkpointer.py`, `run_budget.py` | `test_budget_ledger_store.py::test_fr002_competing_resumes_use_revision_compare_and_swap`; `::test_fr002_parallel_fresh_writers_cannot_both_claim_one_thread`; `::test_fr002_cleared_store_and_old_revision_cannot_resurrect_or_overwrite_a_run`; `::test_fr002_sqlite_write_failure_rolls_back_the_ledger_transaction` |
| S3.4 — restore original cumulative identity and CLI tracker references; lost in-flight usage unavailable; replayed phases optional; independent analyst wrap-up | `run_budget.py`, `graph/trading_graph.py`, `agents/analysts/turn.py` | `test_budget_ledger_store.py::test_fr002_restore_into_empty_tracker_preserves_context_reference_and_run_identity`; `::test_fr002_inflight_recovery_is_committed_when_persistence_is_already_bound`; `::test_fr002_replayed_required_phase_is_an_optional_retry_after_resume`; `test_budget_checkpoint.py::test_fr002_checkpoint_restore_preserves_cli_tracker_instance`; `::test_fr002_usage_between_graph_commits_survives_replay_and_success_cleanup` |
| S3.5 — missing/legacy/invalid accounting gives controlled failed REVIEW without new dispatch or fabricated memory; explicit clear starts a new identity | `graph/trading_graph.py`, `graph/checkpointer.py`, `llm_clients/invocation.py` | `test_budget_checkpoint.py::test_fr002_missing_ledger_refuses_resume_without_model_dispatch`; `::test_fr002_enabling_budget_cannot_treat_legacy_checkpoint_history_as_zero`; `::test_fr002_checkpoint_write_failure_is_controlled_before_dispatch`; `::test_fr002_explicit_checkpoint_clear_authorizes_a_fresh_budget_identity`; `test_budget_termination.py::test_fr002_required_synthesis_failure_is_diagnostic_review_without_uncaught_error` |
| S3.6 — automatic context for direct public stream and manual begin/stream/end; setup failure restores resources and enclosing context | `graph/trading_graph.py`, `llm_clients/invocation.py` | `test_budget_entrypoints_s3.py::test_fr002_direct_public_stream_creates_budget_context_and_restores_caller`; `::test_fr002_public_begin_stream_end_needs_no_manual_observation_scope`; `::test_fr002_public_checkpoint_error_still_restores_automatic_context`; `test_budget_checkpoint_errors.py::test_fr002_public_checkpoint_setup_failure_restores_scope_and_connections`; `::test_fr002_public_begin_with_external_budget_restores_cumulative_history`; `test_budget_invocation.py::test_fr002_explicit_invocation_context_cannot_charge_an_enclosing_run` |
| S3.7 — schema 2 adds seven budget fields; preserve lifecycle and legacy fields; both reports retain unknown usage and non-hard-cap explanation | `run_record.py`, `reporting.py`, `report_html.py`, `graph/trading_graph.py` | `test_budget_reporting.py::test_fr002_budget_results_and_reasons_are_machine_readable_without_changing_status`; `::test_fr002_schema_two_keeps_legacy_keys_and_observations_out_of_replay_settings`; `::test_fr002_no_budget_records_disabled_without_inventing_zero_or_replay_input`; `::test_fr002_schema_one_report_inputs_remain_supported_without_budget_claims`; `::test_fr002_markdown_and_html_report_same_observed_budget_and_unknown_usage`; `::test_fr002_exhausted_diagnostic_report_retains_failed_review_and_reason` |
| S3.8 — valid synthesis survives cleanup failure with completed lifecycle and warning/reason, exhausted precedence retained; terminal canonical record written | `graph/trading_graph.py`, `cli/run.py`, `graph/checkpointer.py` | `test_budget_checkpoint_errors.py::test_fr002_direct_graph_cleanup_failure_keeps_valid_result_and_honest_metadata`; `::test_fr002_cli_cleanup_failure_keeps_valid_result_and_matches_direct_graph_contract` |
| S3.9 — each backtest cell isolated; controlled failed cells not successful; standalone settlement records independent and failures explicit | `backtest.py`, `graph/trading_graph.py`, `memory/settlement.py` | `test_budget_backtest.py::test_fr002_backtest_budget_is_per_cell_and_controlled_failures_are_not_successes`; `::test_fr002_standalone_reflection_record_does_not_overwrite_analysis_metadata`; `test_budget_memory_persistence.py::test_fr002_settlement_ledger_failure_propagates_without_provider_failure_or_later_attempts`; `::test_fr002_standalone_ledger_error_writes_separate_failed_record_and_keeps_entries_pending`; `::test_fr002_standalone_provider_failure_writes_failed_record_without_changing_analysis_usage` |
| S3.10 — no-budget signatures/default behaviour unchanged; output cap, profiles, retries and INV-003 remain separate | `default_config.py`, `graph/trading_graph.py`, `llm_clients/invocation.py`, existing graph routes | `test_budget_checkpoint.py::test_fr002_budget_identity_changes_only_when_enabled`; `test_budget_configuration.py::test_req_fr002_budget_is_independent_of_output_cap_and_profile`; `test_budget_invocation.py::test_fr002_no_budget_preserves_legacy_invoke_shape`; `test_budget_calls.py::test_req_fr002_no_budget_preserves_all_existing_fallback_calls`; existing `test_graph_end_to_end.py` tool-cap/wrap-up cases |

The public durable ledger commits allowlisted cumulative snapshots on every
event, using revision/generation compare-and-swap. It restores identities and
usage before dispatch. A replay of an already started phase is an optional
retry; analyst `.wrap_up` is a separate phase. Lost history cannot become zero.
Manual public stream/checkpoint callers use the same context lifecycle as CLI
and `propagate()` callers. Explicit clearing removes graph and budget history
for the same thread, while disabled `None` preserves historical signatures.

The canonical schema-2 budget fields are `limit`, `enforcement_enabled`,
`status`, `reason_codes`, `known_tokens`, `usage_state`, and `blocked_calls`.
They remain separate from `completed` / `failed` and from replay inputs.
Incomplete historical usage stays partial/unavailable in reports. Cleanup
failure preserves a valid completed synthesis and adds a warning/reason to
the canonical record; exhausted status has precedence. Standalone settlement
records and backtest cell accounting remain independent of the last analysis.

| Requirement / invariant | S3 compatibility evidence |
|---|---|
| REQ-TA-FR-002 | All S3.1–S3.10 rows above; threshold admission remains S1/S2 foundation plus durable replay acceptance |
| REQ-TA-QR-001 | Controlled history/storage failures and retained diagnostics in S3.5/S3.8/S3.9; existing provider/data error tests remain applicable |
| REQ-TA-QR-003 | Public tracker/storage/serializer interfaces registered in AGENTS §6 and ADR-003; no private cross-module SQLite access; existing layering checks retained |
| REQ-TA-QR-004 | S3.7 schema migration, null/incomplete usage, closed lifecycle vocabulary and legacy support; S3.8/S3.9 terminal records |
| REQ-TA-QR-005 | Deterministic offline tests with existing network isolation, scripted doubles and temporary state; full-suite checks remain stage requirements |
| REQ-TA-INV-001 | S3.5 diagnostic REVIEW never becomes a tradeable rating or normal decision memory |
| REQ-TA-INV-002 | Durable settled outcomes and pending skipped entries retained; point-in-time tools/memory tests remain unchanged |
| REQ-TA-INV-003 | S3.4 independent initial/wrap-up phases and S3.10 existing tool cap; budget does not increase allowed tool rounds |
| REQ-TA-INV-005 | Existing material-claim audit/acceptance remains; diagnostic REVIEW cannot claim a new accepted recommendation |
| REQ-TA-INV-007 | Deterministic pre-agent instrument resolution remains under existing identity/symbol tests |

Final-report reserve, quantitative warning thresholds and calibration targets
remain **TBD**. No live/provider or phase-token-share experiment is recorded
by this implementation mapping. Final verification results are appended only
after actual checks, independently of these acceptance-test references.

Final S3 verification (2026-11-18): full `pytest -q` passed **1945 tests,
6 skipped, 1 deselected, 24 warnings and 100 subtests in 60.72s**. The separate
full run with fixed random order seed **20261118** passed the same counts in
**62.21s**. Both ran in isolated temporary directories/environments with
dotenv discovery disabled, UTF-8 mode and the existing network guard. No live
provider request or dependency/configuration change was needed. Whole-repo
Ruff and registry/schema validation passed; final AI-use-log, scope and
tracked/new-file whitespace checks are recorded in the session transcript.
The implementation remains uncommitted on `feat/FR-002`, pending human review.
