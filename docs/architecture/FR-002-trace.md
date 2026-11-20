# REQ-TA-FR-002 — traceability record

- Requirement: `docs/req/requirements.yaml` → REQ-TA-FR-002 (must, implement)
- ADR: `docs/architecture/ADR-004-token-budget.md`
- Related: QR-001, QR-003, QR-004, QR-005; INV-002, INV-003, INV-005, INV-007
- Baseline before this slice: `65c45a5` on `feat/FR002-OpenCode`.
- Status: S1–S3 implemented on `feat/FR002-OpenCode`; verified with `ruff check .`
  and the full offline suite (no regressions; the only failures are pre-existing
  Windows-GBK `read_text()` locale artifacts, reproduced on the baseline).
- Reserve percentage and every quantitative calibration: **TBD** until the
  phase-token-share experiment (requirement-candidates.md §8) is recorded.

## fit_criterion → implementation → test

| fit_criterion clause | Implementation | Tests |
|---|---|---|
| accept a maximum token budget N for one run | `default_config.token_budget` (+ `TRADINGAGENTS_TOKEN_BUDGET`); `graph/trading_graph.py` reads/validates; CLI `--token-budget`; `RunBudgetTracker(limit)` | `test_budget_configuration.py` |
| recorded usage ≥ N blocks every SUBSEQUENT optional call | `run_budget.try_start` (OPTIONAL refused at/over N); `invocation.invoke_with_budget`; `graph/setup.py` optional wrappers; `graph/conditional_logic.py` skip markers | `test_budget_admission.py`, `test_budget_routing.py` |
| run terminates with status ∈ {BUDGET_OK, BUDGET_WARNING, BUDGET_EXHAUSTED} + machine-readable reason | `run_budget.RunBudgetTracker.snapshot`/status computation | `test_budget_status.py`, `test_budget_reporting.py` |
| a single in-flight call may push recorded usage past N (no exact hard cap) | admission lock; overshoot allowed; documented | `test_budget_concurrency.py` |
| provider does not report usage → unavailable, not estimated | `usage.normalize_usage`; `UsageCallbackHandler`; `stats_handler` adapter | `test_budget_usage.py` |
| control failure w/o uncaught exception (QR-001 budget scenario) | `graph/setup.py` controlled skip; `graph/trading_graph.py` failed/REVIEW path | `test_budget_termination.py` |
| QR-004 metadata compatibility; status vocabulary unchanged | `run_record.run_metadata.budget`; `reporting._header`; `report_html._run_details` | `test_budget_reporting.py` + regression `test_run_record.py` |
| final-report reserve percentage: TBD | not implemented; documented | `test_budget_status.py` (no reserve claimed) |

## Call classification

See ADR-004 "Call roles". Optional: analyst follow-up rounds, debate and risk
contributions, structured/JSON/free-text retries and fallbacks, in-graph
reflections. Required: first analyst invocation, analyst wrap-up after it has
started, first Research Manager / Trader / Portfolio Manager synthesis.

## Compatibility preserved

- INV-002 (point-in-time): date path untouched.
- INV-003 (tool-round cap): `_analyst_graph` `more_or_wrap_up`/`wrap_up` keep
  the cap; budget adds an optional gate on top, never bypassing the cap.
- INV-005 / QR-002: budget metadata does not change `final_rating` or the claim
  audit.
- INV-007: ticker resolution untouched.
- QR-004: lifecycle status stays `completed`/`failed`; budget is a separate
  dimension.
- No-budget run: baseline behaviour and checkpoint signature unchanged.

## Files

- New: `src/tradingagents/run_budget.py`, `src/tradingagents/llm_clients/usage.py`,
  `src/tradingagents/llm_clients/invocation.py`; tests `test/offline/test_budget_*.py`.
- Modified: `default_config.py`, `cli/stats_handler.py`, `cli/main.py`,
  `cli/run.py`, `graph/trading_graph.py`, `graph/setup.py`,
  `graph/conditional_logic.py`, `agents/structured.py`,
  `agents/managers/portfolio_manager.py`, `memory/reflection.py`,
  `run_record.py`, `reporting.py`, `report_html.py`.
