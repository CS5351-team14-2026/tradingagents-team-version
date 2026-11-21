# Invariant register

> Deliverable D2.3. Each invariant is a zero-tolerance rule enforced in
> deterministic code, with a negative test that fails when the rule is
> violated and a concrete operational fallback (never "fix the bug"). Status
> per `docs/req/requirements.yaml`: `implemented` = delivered in this project;
> `restate` = baseline behaviour the team commits to keep and verifies;
> `candidate/wont` = not adopted (listed at the end for completeness).

## INV-005 — No untraceable material claim in an accepted report

- **Statement.** An accepted recommendation shall contain no material claim
  that cannot be traced to a source (agent output or dated data).
- **Source requirement.** `REQ-TA-INV-005` (implements `REQ-TA-FR-005`,
  `REQ-TA-QR-002`; definition of a material claim in ADR-001).
- **Enforcing component.** `src/tradingagents/reporting.py`
  (`audit_material_claims`, `evaluate_claim_acceptance`),
  `src/tradingagents/graph/trading_graph.py` (`record_decision`).
- **Verification.** `test/offline/test_traceability_invariant.py`,
  `test/offline/test_claim_acceptance.py` (negative tests: unknown source,
  undated market data, missing metadata, free-text fallback).
- **Operational fallback.** Record `claim_acceptance.status = REJECTED` (or
  `NOT_ENFORCED` when enforcement is explicitly disabled) with the audit reason
  codes on the run record and report header; keep the claims and label the
  unsupported ones `UNSUPPORTED` in both renderings; never present the report
  as an accepted evidence-linked recommendation. The rating is **not** changed
  (`REQ-TA-INV-001` owns rating semantics); the memory-log entry is still
  written so later reflection sees the rejected run.

## INV-001 — Invalid or contradictory ratings produce REVIEW

- **Statement.** A decision with an invalid, missing, contradictory, or
  unreadable rating shall never be presented as a tradeable position.
- **Source requirement.** `REQ-TA-INV-001` (status `restate`; interacts with
  `REQ-TA-FR-004`, ADR-003).
- **Enforcing component.** `src/tradingagents/agents/rating.py`
  (`RATING_REVIEW`, `parse_rating`, `is_review`, `validate_final_decision`).
- **Verification.** `test/offline/test_rating_integrity.py` (negative tests: no
  rating, two conflicting ratings, fullwidth-colon rating → `REVIEW`).
- **Operational fallback.** Mark the run non-actionable, surface `REVIEW` plus
  a human-review notice; never substitute `Hold`.

## INV-002 — Point-in-time data integrity

- **Statement.** A run dated *d* shall never receive data dated after *d*.
- **Source requirement.** `REQ-TA-INV-002` (status `restate`).
- **Enforcing component.** `src/tradingagents/dataflows/date_window.py`
  (`as_of`, `as_of_window`, `withhold_*`), tool layer
  `src/tradingagents/agents/tools.py`, `TradingAgentsGraph._validate_trade_date`,
  memory read filter `src/tradingagents/memory/log.py` (`get_past_context`).
- **Verification.** `test/offline/test_date_boundaries.py`,
  `test/offline/test_tool_date_enforcement.py`,
  `test/offline/test_memory_pointintime.py`.
- **Operational fallback.** Clamp the served window to *d* and emit the
  point-in-time notice; when a vendor cannot honour the bound, withhold the
  data and label it unavailable rather than serving it.

## INV-003 — Maximum tool-round enforcement

- **Statement.** An analyst shall never exceed the configured maximum number
  of tool-call rounds.
- **Source requirement.** `REQ-TA-INV-003` (status `restate`; interacts with
  `REQ-TA-FR-001`, ADR-002).
- **Enforcing component.** `src/tradingagents/graph/setup.py`
  (`_analyst_graph`, `more_or_wrap_up`, `wrap_up`); construction-time check
  `2 * max_tool_rounds + 2 < max_recur_limit` in `trading_graph.py`.
- **Verification.** `test/offline/test_analyst_execution.py`,
  `test/offline/test_graph_end_to_end.py`,
  `test/offline/test_profiles_graph.py` (profile caps applied per analyst).
- **Operational fallback.** Force the wrap-up turn and end the analyst with the
  report it has.

## INV-007 — Deterministic ticker resolution

- **Statement.** The analysed company shall be resolved deterministically from
  the ticker before any agent runs.
- **Source requirement.** `REQ-TA-INV-007` (status `restate`).
- **Enforcing component.** `src/tradingagents/dataflows/symbols.py`,
  `src/tradingagents/agents/context.py` (`resolve_instrument_identity`,
  `build_instrument_context`).
- **Verification.** `test/offline/test_symbols.py`,
  `test/offline/test_symbol_normalization_paths.py`.
- **Operational fallback.** Reject an unresolvable ticker before the run starts
  with a clear error; never let the model pick an instrument.

## Not adopted (kept for completeness)

- `REQ-TA-INV-004` (no silent failure of mandatory agents as a new uniform
  status) — `candidate`/`wont`; the concrete gaps it covered are closed by the
  QR-001 controlled-failure record (ADR-005) and the claim-acceptance verdict.
- `REQ-TA-INV-006` (credential leakage as a declared invariant) — folded into
  `REQ-TA-SEC-001`, which is `implemented` and CI-enforced (ADR-006).
