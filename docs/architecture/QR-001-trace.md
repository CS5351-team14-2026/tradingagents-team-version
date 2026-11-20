# REQ-TA-QR-001 — traceability record

- Requirement: `docs/req/requirements.yaml` → REQ-TA-QR-001 (must, implement #xiaokewei001)
- ADR: `docs/architecture/ADR-005-controlled-failures.md`
- Related preserved: REQ-TA-FR-002 (ADR-004 budget), REQ-TA-QR-004 (run record),
  REQ-TA-INV-001 (REVIEW), REQ-TA-FR-006 (candidate — not implemented)
- Baseline: `8704e06` on `feat/QR001-OpenCode` (includes completed FR-002).
- Status: Q1–Q2 implemented; verified with `ruff check .` and the full offline
  suite (only failures are pre-existing Windows-GBK `read_text()` locale
  artifacts, reproduced on the baseline).

## fit_criterion → implementation → test

The fit_criterion is **scenario coverage** (all five), not a percentage. Each
scenario has one offline, deterministic test using test doubles; each asserts
the status, the machine-readable failure code, a safe diagnostic, the absence of
an uncaught exception, and `final_rating=REVIEW` when no valid call exists.

| Scenario | Code (`run_metadata.failure.code`) | Implementation | Test |
|---|---|---|---|
| provider timeout | `PROVIDER_TIMEOUT` | `graph/trading_graph._run_graph` classify + controlled `(state, REVIEW)`; **CLI stream path** classifies + `typer.Exit` (D-CLI); `failure.classify_exception` | `test_qr001_provider_timeout.py`, `test_qr001_cli_timeout.py` |
| agent returns invalid JSON | `INVALID_AGENT_JSON` | `agents/structured.py` classification; controlled empty/REVIEW report | `test_qr001_invalid_json.py` |
| missing API key | `MISSING_API_KEY` | `TradingAgentsGraph.__init__` typed `MissingApiKeyError`; CLI catches + writes record | `test_qr001_missing_api_key.py` |
| stock data unavailable | `STOCK_DATA_UNAVAILABLE` | `data_signal` per-run holder set from core-data sentinels; `_run_graph` **and** CLI `_terminal_failure` downgrade to REVIEW + record (D-D1) | `test_qr001_stock_data_unavailable.py` (end-to-end) |
| token budget exhausted | `TOKEN_BUDGET_EXHAUSTED` | FR-002 statuses (ADR-004) mirrored on the review path + record `failure.code` | `test_qr001_budget_exhausted.py` |

## Record contract (D-C)

```
run_metadata.status: completed | failed          # unchanged (QR-004)
run_metadata.failure: { code, phase, diagnostic, exception_type? }   # allowlisted
final_rating: REVIEW                             # when no valid tradeable call
run_metadata.budget.status: BUDGET_OK | BUDGET_WARNING | BUDGET_EXHAUSTED
```

`diagnostic` is a fixed safe message; no raw exception text, endpoint, key, or
local path is recorded (D-E; REQ-TA-SEC-001 intent).

## Compatibility preserved

- FR-002 logic (`run_budget.py`, `usage.py`, `invocation.py`, call admission):
  untouched; `TOKEN_BUDGET_EXHAUSTED` is a metadata mirror only.
- QR-004 lifecycle `completed`/`failed`: unchanged vocabulary.
- INV-001 REVIEW rule: reused.
- INV-002/003/005/007: untouched.
- Missing key surfaces as a `ValueError` subclass — existing `except ValueError`
  callers keep working.

## Files

- New: `src/tradingagents/failure.py`; `docs/architecture/ADR-005-controlled-failures.md`,
  this trace; `test/offline/test_qr001_*.py` (seven files: five scenarios + FR-008 reconcile + CLI timeout).
- Modified: `graph/trading_graph.py`, `agents/structured.py`, `run_record.py`,
  `reporting.py`, `report_html.py`, `cli/run.py`, `llm_clients/openai_client.py`
  (typed key error, with ADR-005 reference per the safety-path guard),
  `CHANGELOG.md`, `docs/ai-use-log.yaml`, and two updated tests
  (`test_graph_end_to_end.py`, `test_run_record.py`) for the D-A contract.
