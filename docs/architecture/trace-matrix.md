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

## FR-007 / PERF-001 — evaluation slice

| Requirement | Component | Test | Monitor / evidence |
|---|---|---|---|
| REQ-TA-FR-007 | `evaluation.py`, `evaluation_runner.py`, `cli/main.py::compare` | `test_evaluation.py`, `test_evaluation_runner.py` | Raw paired JSON/CSV: settings, timings, calls, tokens, ratings, confidence and completion; absent usage explicit |
| REQ-TA-PERF-001 | `ComparisonResult.summary`, paired runner monotonic timing | `test_evaluation_runner.py::test_three_cases_repeated_and_isolated`, failure retention tests | Successful paired medians/min/max/counts, failed counts; target TBD, real Quick-profile experiment pending |

Scope: offline-verified tooling; no claim of measured production speedup or full
PERF-001 acceptance. Public interfaces only; no change to claim/rating semantics.
