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

No entries yet — the first entry lands with the first significant bug found
during implementation rounds.

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
