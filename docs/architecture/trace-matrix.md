# Trace matrix — FR-005 / QR-002 / INV-005

Only the requirements this slice implements are listed. The authoritative
registry is `docs/req/requirements.yaml`; the claim contract is ADR-001.

| Requirement | Component | Test | Monitor |
|---|---|---|---|
| REQ-TA-FR-005 (evidence-linked recommendation, dated observations, unsupported labels, notice) | `agents/schemas.py` (`MaterialClaim`, `PortfolioDecision.supporting_factors` / `opposing_factors`, `render_pm_decision`); `agents/managers/portfolio_manager.py`; `reporting.py` (`render_claim_ledger`, `NOT_INVESTMENT_ADVICE`); `report_html.py` | `test/offline/test_material_claims.py`; `test/offline/test_claim_traceability.py`; `test/offline/test_report_disclaimer.py`; `test/offline/test_report_html_claims.py` | Report header `Traceability:` line; markdown `## Evidence Linkage` ledger; HTML `Evidence Linkage` section; disclaimer in both renderings |
| REQ-TA-QR-002 (material-claim attribution fraction; source and producing agent identifiable) | `reporting.py` (`source_vocabulary`, `audit_material_claims`, `render_claim_ledger`) | `test/offline/test_claim_traceability.py`; `test/offline/test_material_claims.py`; `test/offline/test_report_html_claims.py` | `claims_attributed` / `claims_total` in the audit and report header; sampled human claim audit (row-3 measurement still TBD) |
| REQ-TA-INV-005 (no untraceable material claim in an accepted report) | `reporting.py` (`audit_material_claims` status and reason codes) | `test/offline/test_traceability_invariant.py` | `DOWNGRADED` + reason codes; `UNSUPPORTED` labels in both renderings; `claim_audit` in `AgentState` (run-path wiring deferred) |

`ClaimAudit` status is a report-level traceability status; it does not affect
`final_rating` or the REVIEW rule (REQ-TA-INV-001 / REQ-TA-FR-004).

## QR-003 — maintainability and dependency boundaries

| Requirement | Component | Test | Monitor / CI |
|---|---|---|---|
| REQ-TA-QR-003 (new components free of boundary violations; lint and offline suite pass; LLM/data replaceable by test doubles) | Structural check over `agents`, `graph`, `dataflows`, `memory`, `llm_clients` for **statically parseable** cross-component private imports and alias reads (public and own-component private allowed; absolute/relative private import, private-module imports, and `alias._x` / package-alias / full-path reads rejected; scope- and statement-order-aware resolution; new modules auto-scanned; dynamic access such as `getattr`/`importlib` is out of static scope) — `test/offline/test_layering.py`; retained vendor-layering rule | `test_layering.py::test_no_component_reaches_into_anothers_private_names`; `::test_public_cross_component_import_passes`; `::test_own_component_private_import_passes`; `::test_cross_component_private_import_absolute_fails`; `::test_cross_component_private_import_relative_fails`; `::test_importing_private_module_from_other_component_fails`; `::test_importing_private_submodule_from_other_component_fails`; `::test_cross_component_private_import_from_package_init_fails`; `::test_cross_component_private_alias_read_fails`; `::test_cross_component_private_read_via_package_alias_fails`; `::test_same_alias_name_in_different_files_is_independent`; `::test_function_local_import_private_read_in_same_function_fails`; `::test_function_local_import_does_not_leak_into_other_functions`; `::test_statement_order_rhs_reads_previous_binding_before_assignment`; `::test_multiline_rhs_call_resolves_before_assignment`; `::test_next_statement_same_line_reads_new_local_binding`; `::test_for_target_binds_after_iterable_before_block`; `::test_with_as_target_binds_after_context_expr_before_block`; `::test_a_newly_added_module_is_scanned`; `::test_vendor_libraries_are_imported_only_by_the_data_layer` | CI gate 2 `ruff check .`; CI gate 5 full offline `pytest -q` (`test-layering` / regression) |
| REQ-TA-QR-003 (LLM/data dependencies replaceable by test doubles in unit tests) | `agents/graph` run path; `ScriptedModel` (LLM double) + fixed market-data fixture (`offline`) | `test_graph_end_to_end.py::test_a_full_run_reaches_a_logged_decision[free-text]` and `[structured]` (asserts `model.calls` non-empty, market-data double called, report produced) | CI gate 5 full offline suite |

Scope: QR-003 is a cross-cutting verification requirement enforced over the
statically parseable cross-component private imports and alias reads; dynamic
access (`getattr`/`importlib`, runtime-passed values) is outside static reach.
This slice adds only offline tests and does not change runtime behaviour.
Boundary exceptions are not needed (the baseline is clean over the five
components).

## QR-004 — structured run metadata and observability

| Requirement | Component | Test | Monitor / CI |
|---|---|---|---|
| REQ-TA-QR-004 (every run records complete structured metadata: profile, models/providers, analysts, rounds, vendors, token totals, status) | `run_record.py` (`RECORD_SCHEMA_VERSION`, `RunRecord`, `UsageSummary`, `build_run_record`, `build_usage_summary`); `graph/trading_graph.py` (`run_settings()` canonical record, `set_run_observations()`, `write_run_record()`, `_run_graph` failure path); `reporting.py` (`_header`, `_token_usage_line`); `cli/run.py` (observations from `StatsCallbackHandler`, failure-path write) | `test/offline/test_run_record.py` (20 tests: schema version + sections, replayable/observational separation, profile null, usage aggregation, unavailable = null + usage_complete false, partial usage not a total, status values + rejection, deterministic serialization, no secret/path, legacy keys, report header complete/unavailable, write_run_record failed status + no secret/path, `_run_graph` failed+re-raise, `_run_graph` completed, persisted observations not defaults) | Report header `Run status:` + `Tokens:` lines; on-disk `run_record_<date>.json` (failure) and `full_states_log_<date>.json` `run_settings` (success); CI gate 5 full offline suite |

Scope: QR-004 adds a canonical, versioned run record (migration strategy C: nested
`replayable_settings` + `run_metadata` sections, legacy flat keys retained for one
schema version). Status vocabulary is exactly `completed`/`failed` (approved A2);
unavailable usage is `usage_complete=false` with null token totals (approved A3),
rendered as "unavailable" in reports. Observational values (tokens, status,
timestamps) are never part of `replayable_settings` (that is FR-008's future input,
not implemented here).

## FR-007 / PERF-001 — evaluation slice

| Requirement | Component | Test | Monitor / evidence |
|---|---|---|---|
| REQ-TA-FR-007 | `evaluation.py`, `evaluation_runner.py`, `evaluation_checkpoint.py`, `cli/main.py::compare` | Offline arithmetic/runner/Quick/recovery/integration tests, `test_evaluation_controlled_failures.py` (QR-001 returned failures excluded); [18-run real evidence](../evidence/perf001-2026-11-21-final/README.md) | JSON/CSV, per-attempt journal, acceptance, complete usage/confidence and safe errors; source-matched resume |
| REQ-TA-PERF-001 | Paired runner monotonic timing; `ComparisonResult.summary`; ADR-007 | [3 cases x 3 repeats x 2 configs](../evidence/perf001-2026-11-21-final/README.md), independent statistics/CSV check | Median baseline 417.79s, Quick 323.48s, reduction 22.57%; min/max/N/failures disclosed; threshold proposal for human review |

Scope: offline-verified tooling and the linked frozen-source common-cap real
experiment. This is measured execution under recorded conditions, not a universal
production latency guarantee or approval of rejected investment reports. Targets
and protocol qualification require human PR review; audit/rating rules stay fail-closed.

## FR-008 — settings replay from a prior run record

| Requirement | Component | Test | Monitor / CI |
|---|---|---|---|
| REQ-TA-FR-008 (re-run an analysis using the exact settings recorded for a prior run; configuration reproducibility only) | `settings_replay.py` (`SUPPORTED_SCHEMA_VERSION`, `ALLOWED_KEYS`, `OPTIONAL_DEFAULTS`, `ReplaySettings`, `load_replayable_settings`, input-format extraction + strict validation); `cli/main.py` (`--from-settings` + conflict rejection, combinable with `--token-budget`); `cli/run.py` (`_selections_from_replay`, replay branch: `profile=None` + recorded resolved analysts/rounds as explicit overrides, then the shared FR-002 tracker) | `test/offline/test_settings_replay.py`; `test/offline/test_fr008_fr002_reconcile.py` | `run_settings()` of the replayed run is the report-metadata evidence; CI gate 5 full offline suite |

Scope: FR-008 reads only `run_settings()["replayable_settings"]` (and
`schema_version`) from a prior QR-004 record — never `run_metadata`, ticker,
analysis date, output paths, credentials, or endpoints. Execution is
reconstructed with `profile=None` and the recorded resolved analysts/round
limits, so the profile mapping is not re-applied; the recorded resolved values
are authoritative. Reproducibility is of configuration only and does not
guarantee identical market data, provider responses, sampled LLM output, timing,
token usage, confidence, or final recommendation.

`token_budget` is owned by REQ-TA-FR-002 and is an execution-time safety
control: it is recorded under `run_metadata.budget`, is NOT part of the FR-008
v1 allowlist, and is NOT replayed. A replayed run's budget comes only from the
new invocation (`--token-budget`/env), and it flows through the same FR-002
`StatsCallbackHandler`/`RunBudgetTracker` construction so there is one ledger
and no duplicate accounting.

## QR-001 — controlled failure scenarios

| Requirement | Component | Test | Monitor / CI |
|---|---|---|---|
| REQ-TA-QR-001 (five controlled failure scenarios end with a defined status + safe diagnostic + zero uncaught exceptions) | `failure.py` (`FailureCode`, `build_failure`, `classify_exception`, `MissingApiKeyError`); `graph/trading_graph.py` (`_run_graph` classify → controlled `(state, REVIEW)`, budget-exhausted REVIEW mirror, missing-key at construction); `agents/structured.py` (parse/fallback no escape); `cli/run.py` (missing-key catch + record); `run_record.py` (`run_metadata.failure` allowlist); `reporting.py` / `report_html.py` (Failure line) | `test_qr001_provider_timeout.py`, `test_qr001_invalid_json.py`, `test_qr001_missing_api_key.py`, `test_qr001_stock_data_unavailable.py`, `test_qr001_budget_exhausted.py`, `test_qr001_fr008_reconcile.py` | `run_metadata.failure{code,phase,diagnostic,exception_type?}`; report `Failure:` line; CI gate 5 full offline suite |

Scope: `run_metadata.failure` is a separate, observational, allowlisted block
(`completed`/`failed` lifecycle unchanged, QR-004). It is never in
`replayable_settings`, so a record stays replayable by FR-008. Only *classified*
failures (timeout/transport, parse) are controlled into `(state, REVIEW)`; an
unclassified exception is still re-raised (a genuine bug stays visible). The
budget-exhausted code is a mirror of FR-002's `BUDGET_*` status on the REVIEW
path; FR-002 logic is unchanged.
## FR-004 / INV-001 — final-decision validation

Contract: ADR-003. Approved test plan: Issue #32.

| Requirement | Component | Test | Monitor / evidence |
|---|---|---|---|
| REQ-TA-FR-004 (validate rating + prices before adoption) | `agents/rating.py` (`validate_final_decision`, `normalise_price` with the ASCII-only price grammar that rejects `.5`/fullwidth/oversized integers, reason constants); `agents/schemas.py` (`PortfolioDecision.entry_price`/`stop_loss` as raw `Any`, `decode_strict_json`, `raw_model_text`, `decision_raw_mapping`, `build_decision`); `agents/managers/portfolio_manager.py` (`_structured_with_raw`, `_invoke_json_mode` with `include_raw=True` raw-body strict decode, `_json_mode_payload`, node free-text price validation); `agents/structured.py` (retry gate); `graph/trading_graph.py` (`_log_state` persists `final_prices`); `reporting.py` (`review_summary_text`, `decision_display_text`, `_report_parts` REVIEW substitution, header review reasons); `report_html.py` (body via `_report_parts`); `cli/display.py` (`display_complete_report` uses `decision_display_text`); `cli/run.py` (review notice) | `test/offline/test_final_decision_validation.py` (FR004-01/02/03/05/06/07 unit + end-to-end, incl. FR004-03 `.5`/fullwidth/oversized-int → REVIEW without OverflowError and FR004-01 `final_prices` in the final state and run-state JSON); `test/offline/test_decision_validation_routes.py` (FR004-05 routes: structured, JSON-mode, decode-miss, budget); `test/offline/test_fr004_regression.py` (post-PR #52 defects: prose Buy/Overweight → REVIEW + two missing reasons; bare `NaN`/`Infinity`/`-Infinity` at the real wrapper's raw-response layer → decode miss under the token budget; decoded `float('nan')` → `invalid_*` without retry; REVIEW summary across CLI/Markdown/HTML including an old saved REVIEW state) | `decision_review_reasons` in the PM state and the state log; `- Review reasons:` header line; HTML `span.rating` = `REVIEW` and REVIEW summary in the body; CLI review notice and REVIEW summary in the `V. Portfolio Manager Decision` panel; `final_prices` (validated floats) in the final state and `full_states_log_<date>.json`, `{}` on REVIEW |
| REQ-TA-INV-001 (a non-resolvable rating is never a tradeable position) | `agents/rating.py` (`extract_rating`, `parse_rating`, `validate_final_decision` unresolved short-circuit) | `test/offline/test_rating_integrity.py` (unchanged); `test/offline/test_final_decision_validation.py::test_an_unresolved_rating_short_circuits_to_unresolved`; `test/offline/test_final_decision_validation.py::test_a_bare_non_finite_token_fails_strict_decoding` | `final_rating=REVIEW` with `["unresolved_rating"]`; no `invalid_*`/`missing_*` inferred from an undecodable body |

## QR-005 — offline testability (offline, network-free, order-independent)

Approved test plan: Issue #32. Evidence: `docs/evidence/qr005_offline_evidence.txt`.

| Requirement | Component | Test | Monitor / CI |
|---|---|---|---|
| REQ-TA-QR-005 / QR005-01 (default selection collects offline, excludes integration) | `pyproject.toml` selection (`testpaths`, `-m "not integration"`) | `test/offline/test_offline_selection.py` (subprocess `--collect-only`: only `test/offline/...`, `TestDeepSeekLiveStructuredOutput` excluded) | `pytest --collect-only -q` shows 1 deselected (the integration case) and 0 `test/live` nodes |
| REQ-TA-QR-005 / QR005-02 (pytest guard refuses external before real DNS/connect; narrow 127.0.0.1 exception kept) | `test/offline/conftest.py` `_no_network` (socket/DNS + `curl_cffi` sync/async; `requests`/`urllib` ride the socket layer) | `test/offline/test_suite_isolation.py` (probes: connect, connect_ex, dns, curl_cffi, curl_cffi_async, requests, urllib; `test_the_guard_refuses_before_a_real_connection_happens`); `test_chatgpt_auth.py::test_the_browser_answer_reaches_the_loopback_and_strays_are_ignored` (narrow loopback) | OSError("reach the network") before the lower socket/DNS call |
| REQ-TA-QR-005 / QR005-03 (isolated env: external blocked, loopback OK, full suite) | `tools/ci/isolation_preflight.py` (runs outside pytest); `tools/ci/controlled_endpoint.py` (temporary TCP endpoint) | `test/offline/test_isolation_preflight.py` (mocked probes; positive+negative paths); `test/offline/test_controlled_endpoint.py` (local bind/accept) | Final controlled run on a clean snapshot (HEAD d650164 + tree 0000a315…), per-round temp HOME/XDG/TMPDIR, provider + TRADINGAGENTS_* cleared: `unshare -Urn` + `ip link set lo up`, controlled endpoint `172.18.110.113:<port>` reachable outside the ns, unreachable inside (`ENETUNREACH`), `127.0.0.1` bind/connect OK; isolated preflight PASSED every round — see `docs/evidence/qr005_offline_evidence.txt` |
| REQ-TA-QR-005 / QR005-04 (default vs seed 42/5351: same set, order differs, seed reproducible) | `tools/ci/pytest_seeded_order.py` (`-p ... --order-seed N`); `tools/ci/compare_orders.py` (junitxml order) | `test/offline/test_seeded_order_plugin.py` (11); `test/offline/test_compare_orders.py` (5, synthetic junitxml) | Final controlled run, `unshare -Urn`, full suite as separate processes: default/42/5351/42-repeat each 1865 passed 1 skipped (exit 0); `compare_orders.py` PASSED (identical sets, default!=42, default!=5351, 42==42-repeat) — see evidence file |

Scope: QR-005 is cross-cutting verification. This slice adds only test tooling under `test/offline/` and `tools/ci/`; it does not change runtime behaviour. The pytest guard is the always-on in-suite layer; the network-namespace egress block (`unshare -Urn`, loopback only) is the independent environment layer. Both the container-style containment and the full-suite random-order run are verified locally in that isolated namespace (see `docs/evidence/qr005_offline_evidence.txt`); the CI `qr005-isolation` job was withdrawn.

## SEC-001 — secret redaction and leakage prevention

| Requirement | Component | Test | Monitor / CI |
|---|---|---|---|
| REQ-TA-SEC-001 (no configured secret appears unredacted in logs, reports, prompts, fixtures, commits, transcripts) | `redaction.py` (`redact_text`, `redact`, `redact_exception`, `REDACTED`); `cli/main.py` (sanitized error render); `cli/run.py` (two `message_tool.log` write points); `graph/trading_graph.py` (sanitized warning logs); `.github/workflows/ci.yml` `secret-scan` + `.secrets.baseline` | `test/offline/test_sec001_redaction.py` (37 tests: key/token/header/url/env/pem/path shapes, nested/non-string/unicode/malformed, idempotency, false-positive resistance, message_tool.log boundary, CLI error sanitization, gate logic) | CI job `secret-scan` (pinned detect-secrets 1.5.0, baseline-compared); see `docs/architecture/SEC-001-trace.md` |

Scope: high-confidence secret shapes only; the shared sanitizer copies rather than
mutates, is safe on malformed input, and does not read environment variables or
record which value triggered redaction. QR-004 and FR-008 schemas are unchanged;
their existing secret/path exclusions are regression-tested. The detect-secrets
gate pages against a reviewed baseline so only NEW findings block a PR.
