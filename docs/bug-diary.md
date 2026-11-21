# Bug diary — one entry per significant bug (deliverable D4, project.pdf p6)

Format (append below, newest last). Every significant bug gets: symptom,
reproduction, classification, root cause, fix, and — most importantly — which
invariant/requirement gap it exposed.

```
## BUG-NNN — <short title> (date, PR #)

- Symptom:
- Reproduction:
- Classification: <e.g. logic, integration, AI-output handling, data>
- Root cause:
- Fix:
- Invariant/requirement gap exposed:
```

## BUG-001 — FR-004 gate leaves REVIEW non-actionable results as tradeable calls (2026-11-20, follow-up to PR #52)

- Symptom: after the FR-004 slice (PR #52) three paths still presented a
  non-validated decision as a tradeable call: (1) when structured and JSON-mode
  both missed, a plain-text `Buy`/`Overweight` was adopted with no prices and no
  review reasons; (2) a real JSON-mode response carrying a bare
  `NaN`/`Infinity`/`-Infinity` was parsed by LangChain's own `json.loads` into a
  `float('nan')` and misread as a supplied `invalid_*` price instead of a decode
  miss; (3) with a top-level `REVIEW`, the report §V, the HTML body and the CLI
  panel still printed the model's `Rating: Buy` and its entry instruction.
- Reproduction: `test/offline/test_fr004_regression.py` (written against the
  PR #52 integration). The first run was 9 failed / 2 passed: prose Buy/Overweight
  returned `Buy`/`Overweight`; bare `NaN` via the real wrapper returned
  `['invalid_entry_price','invalid_stop_loss']`; and the Markdown/HTML/CLI
  decision regions never showed `REVIEW`.
- Classification: AI-output handling (structured/JSON/free-text decoding and the
  boundary between a decode miss and an invalid value); acceptance path
  validation; report/CLI rendering.
- Root cause: (1) the free-text branch read the rating but never ran the price
  policy; (2) the strict-decode guard only saw a *string* body, while the real
  wrapper returns an already-parsed `PortfolioDecision`, so the bare token was
  never judged at the raw-response layer; (3) the rendered decision text was the
  model's own `render_pm_decision`, never reconciled with `final_rating=REVIEW`.
- Fix: (1) free-text rating is run through `validate_final_decision(rating, {})`
  (Hold/Underweight/Sell pass; prose Buy/Overweight → REVIEW with both missing
  reasons); (2) `_invoke_json_mode` binds with `include_raw=True` and strict-
  decodes the raw `AIMessage` text first (bare token → decode miss under the
  existing token budget); an already-decoded non-finite float stays `invalid_*`
  with no retry; (3) `reporting.py::decision_display_text` produces one REVIEW
  summary (rating + reasons), used by `_report_parts` (Markdown + HTML) and
  `cli/display.py`, reconciled on read so an old saved REVIEW state is covered.
- Invariant/requirement gap exposed: REQ-TA-FR-004's acceptance contract was
  verified against string replies, not the provider's parsed value or its raw
  response, and the "presented as a tradeable call" half (REQ-TA-INV-001) was
  only enforced on the header/state, not on the decision region the reader sees.
  The lesson: test at the real boundary (raw HTTP / parsed instance) and assert
  the rendered surface, not just persisted state.

## BUG-002 — `max_tool_rounds` below 1 made the round cap vacuous (2026-11-17, PR #35)

- Symptom: a profile could resolve `max_tool_rounds` to 0 or a negative value;
  the analyst still made its first tool call, which the cap was meant to forbid.
- Reproduction: resolve a profile/explicit value of 0 and run an analyst that
  requests a tool; `test_profiles_graph.py` and
  `test_checkpoint_lifecycle.py` exercise the guard.
- Classification: input validation / boundary.
- Root cause: profile resolution validated names and the mapping but not the
  lower bound. The wrap-up router fires only after a tool round
  (`rounds >= cap`), so with `cap <= 0` the first tool call always exceeds the
  limit before the router can stop it.
- Fix: reject `resolved.max_tool_rounds < 1` before any model client is built,
  naming the offending value (Implements: ADR-002; REQ-TA-FR-001, INV-003).
- Invariant/requirement gap exposed: INV-003 stated "never exceed
  `max_tool_rounds`" but assumed a positive cap. A boundary value made the
  invariant vacuous. Validate an invariant's parameters, not only its counter.

## BUG-003 — resume of a pre-#27 checkpoint failed after the `claim_enforcement` default flip (2026-11-17, PR #35)

- Symptom: a checkpoint saved right after PR #27 could not be resumed on a
  build whose `claim_enforcement` default is `True`; the run silently started
  fresh instead of continuing.
- Reproduction: save a checkpoint with the then-default `False`, then begin a
  resume with the new default; `test_checkpoint_lifecycle.py`.
- Classification: integration / run identity.
- Root cause: PR #27 added `claim_enforcement` to the config and the settings
  digest was built from "config minus a denylist", so the new key entered the
  signature. A later default flip changed the digest for the same run inputs.
- Fix: exclude `claim_enforcement` from the current signature and rebuild the
  historical digest with the historical value only when the other effective
  inputs match (Implements: ADR-002; REQ-TA-FR-001).
- Invariant/requirement gap exposed: the checkpoint identity contract relied on
  a denylist; adding a config key silently changed every run's identity. The
  digest should be an explicit allowlist.

## BUG-004 — structured output fell back to free text on the first miss (2026-11-16, commits d9fb8b3 / a5a48c0 / eb5c279)

- Symptom: a thinking model answered in plain text instead of calling the
  structured-output tool; the first miss immediately produced a free-text
  decision with no claim metadata, so the audit reported `NOT_ASSESSED` and the
  run was rejected.
- Reproduction: a scripted model returning plain text on the first call and a
  valid decision on the second; `test_structured_agents.py`.
- Classification: AI-output handling.
- Root cause: no retry around the structured invocation, no JSON-mode fallback,
  and no marker distinguishing "model chose not to emit claims" from "structured
  call failed".
- Fix: retry once, then a JSON-mode retry (with an explicit JSON instruction
  added after a real HTTP 400), and record `claim_fallback="free_text"` so the
  audit reports `PM_FREETEXT_FALLBACK`.
- Invariant/requirement gap exposed: a deterministic checker can only be honest
  if the producer records *why* metadata is missing. INV-005's "never
  NOT_ASSESSED as acceptance" depends on that marker.

## BUG-005 — `material_claims` omitted from the state log (2026-11-16, commit 796f4b4)

- Symptom: a saved run could not be re-audited offline: the state log carried
  the aggregate `claim_audit` but not the claims it was computed from.
- Reproduction: run the graph, open the state log, search for
  `material_claims`; `test_claim_audit_recording.py`.
- Classification: observability / traceability.
- Root cause: the state-log serializer used an allowlist of text keys and the
  new `material_claims` field was not added to it.
- Fix: serialize `material_claims` in the state log; add the assertion to the
  recording test.
- Invariant/requirement gap exposed: QR-002 evidence must include the claims
  themselves, not only the verdict — otherwise the audit is not independently
  verifiable.

## BUG-006 — QR-005 test helpers unimportable under the bare `pytest` entry point in CI (2026-11-20, PR #53)

- Symptom: CI failed importing `tools.ci.pytest_seeded_order`; the same command
  worked locally via `python -m pytest`.
- Reproduction: run `pytest` (console script) from the repo root instead of
  `python -m pytest`.
- Classification: packaging / CI environment.
- Root cause: the console script does not add the working directory to
  `sys.path`, and the seeded-order plugin imports a repository helper.
- Fix: `pythonpath = ["."]` in the pytest configuration; log entry recorded.
- Invariant/requirement gap exposed: QR-005 requires the offline suite to pass
  in *the invocation CI uses*, not only in the developer's invocation.

## BUG-007 — SEC-001 redaction missed the durable write surfaces (2026-11-21, commit aadc562)

- Symptom: review found that agent-generated free text (reports, plans,
  decisions) was written to the state log and reports without the redaction
  layer the CLI already applied.
- Reproduction: inject a key-shaped string into an agent report, run the graph,
  read the state log.
- Classification: security / output boundary.
- Root cause: redaction was implemented at the CLI boundary only; the durable
  write surfaces were not in scope of the first slice.
- Fix: sanitize the state-log text keys at write time, redact report inputs, and
  extend the redaction suite (37 tests total).
- Invariant/requirement gap exposed: SEC-001's scope names logs, reports and
  transcripts — the invariant was satisfied on the visible surface but not on
  the durable one. Enumerate every write boundary, not the obvious one.

## 2026-11-21 — FR-007 live evaluation exposed integration defects

- **PM JSON retry HTTP400 (FR-004/FR-007; ADR-003).** A real Quick run reached
  free-text fallback and was REJECTED. A two-request real probe isolated the
  endpoint precondition: the PM JSON-mode retry lacked an explicit JSON prompt
  instruction; tool-mode schema binding does not supply that instruction for
  JSON mode. Fix: append JSON output instruction and the existing PortfolioDecision
  schema only to that retry. Negative HTTP-contract test and strict NaN control:
  `test_pm_json_contract.py`. The human explicitly approved this scope expansion.
- **Four supporting claims (FR-005/INV-005; ADR-001).** A later NVDA report
  contained 4 supporting and 3 opposing claims and was correctly REJECTED with
  CLAIM_LIMIT_EXCEEDED. The producer schema described three but imposed no bound.
  Fix: max_length=3 on each list, causing malformed outputs to follow the existing
  structured retry/fallback path. No slicing, fake acceptance, or audit relaxation.
  Negative schema tests: `test_evaluation_integration_contracts.py`.
- **Persisted usage missing (QR-004/FR-002/FR-007; ADR-004).** Comparison callbacks
  saw complete tokens while direct graph full-state metadata was null. The graph
  had no shared usage handler for direct callers, and attached its ledger after
  persistence. Fix: per-run shared handler or compatible caller ledger, callback
  propagation, and attachment before terminal persistence (including failures).
  Real-graph mocked-provider tests cover both direct and CLI-style callers.
- **Interruption repeats completed work (FR-007/PERF-001).** Pair-level checkpoints
  did not preserve an independently finished side. Fix: atomic per-run journal,
  strict source/input fingerprint, directory ownership and explicit failed-run
  retry. Recovery tests demonstrate no re-billing of completed work and retention
  of failed attempts. Network connection failures remain external failure modes;
  recovery mitigates them without claiming they can never occur.

Detailed diagnosis, source revisions and raw private reports stay in the sibling
local log directories per human instruction. Published evidence includes safe
measurements and limitations, not credentials or private full reports.

## 2026-11-21 — returned controlled failures looked like fast successful runs

- Requirements: REQ-TA-FR-007 / PERF-001; integration REQ-TA-QR-001 / QR-004.
- Trigger: merge the QR-001 contract, where a provider timeout or structured parse
  failure returns REVIEW and a safe failure block instead of raising.
- Gap: the evaluator initially only caught exceptions, so it marked this return
  as completed. Fifteen new negative cases reproduced the mistake before repair.
- Fix: inspect public run metadata and returned run_failure; failure-marked runs
  stay in raw measurements but cannot enter successful-pair speedups. Preserve
  partial observed tokens and keep ordinary claim rejection separate.
- Verification: test_evaluation_controlled_failures.py covers all five codes via
  state/metadata/lifecycle, review-only completion, and real graph timeout usage
  persistence. Full post-merge regression recorded in the review memo.
