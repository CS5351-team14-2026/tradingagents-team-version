# ADR-003 — Validate the final decision before it is adopted

Status: accepted (FR-004 / INV-001 slice; approved test plan Issue #32).
Implements: REQ-TA-FR-004; REQ-TA-INV-001.

## Context

The Portfolio Manager's decision reached the run as a five-tier rating and two
price levels. Before this slice the rating was read and the prices were not
checked: a decoded decision was adopted whole, and a decision nobody could read
fell back to free text whose rating was read from prose. The rating half was
already safe (ADR-001's `REVIEW`, `agents/rating.py`), but the price half was
not, and a decision with a fabricated or mis-parsed level could be presented as
a tradeable call (REQ-TA-FR-004, `project.pdf` p3).

The final-decision answer is produced on up to four paths, in order:
`structured` (schema binding) with one retry, then a `json_mode` retry, then a
free-text fallback. Each intermediate answer was being validated by Pydantic as
it was parsed, which is the wrong place: a price the model wrote as `"15%"`
fails Pydantic, and a coerced value is indistinguishable from an omitted one.

## Decision

1. **Validate after decoding, before adoption.** A decision that decodes is
   validated as a whole by `agents/rating.py::validate_final_decision`. Only the
   final structured or JSON-mode answer is validated; no later attempt is made
   to borrow a price from the Trader's proposal, an analyst report or prose.

2. **Read the raw price the model wrote.** `PortfolioDecision.entry_price` and
   `stop_loss` are declared `Any`, so the value reaches the validator
   uncoerced; an invalid price can be told from a missing one. A validated
   instance (`model_fields`) or a decoded mapping/JSON text is accepted through
   `schemas.py::decision_raw_mapping`. No adoption flag, copying or merging is
   introduced.

3. **Per-rating price policy.** Both prices are required for Buy and Overweight;
   they are optional for Hold, Underweight and Sell. A supplied price must
   normalise to a finite, strictly positive `float` (JSON number or trimmed
   numeric string; binary64 rounding, no exact-decimal or tick-size guarantee).

4. **Review reasons are stable strings.** `decision_review_reasons` is a list:
   `unresolved_rating`, or `missing_entry_price` / `missing_stop_loss` /
   `invalid_entry_price` / `invalid_stop_loss`, accumulated entry-then-stop, one
   code per field. At least one reason means `final_rating=REVIEW`. An unresolved
   rating short-circuits to `["unresolved_rating"]` before the price policy.

5. **Decoded-but-invalid is terminal.** A decision that decodes and fails price
   validation returns `REVIEW` with its reasons and **does not retry**.

6. **Undecodable is a miss.** A body that does not decode — including raw JSON
   with a bare `NaN`, `Infinity` or `-Infinity` token (refused by
   `schemas.py::decode_strict_json`) — follows the existing retry/fallback
   sequence and the existing REQ-TA-FR-002 budget gates. The final reason comes
   from whatever response actually arrived; a rejected body contributes no
   field-specific code. The bare-token check runs at the **raw-response layer**:
   the JSON-mode binding is made with `include_raw=True` and the untouched
   `AIMessage` text is strict-decoded *before* the provider parser's value is
   trusted, because LangChain's own `json.loads` would otherwise turn a bare
   `NaN` into a `float('nan')` and hide the decode failure. A body that *does*
   decode but whose (already-decoded) price is non-finite is the contrast: it is
   a supplied `invalid_*` price and does not retry (see §5).

7. **The free-text fallback is price-validated too.** A prose answer carries no
   price levels, so its rating is run through the same
   `validate_final_decision(rating, {})` the decoded paths use: a prose-only
   `Buy`/`Overweight` (which requires both prices) becomes `REVIEW` with
   `missing_entry_price`/`missing_stop_loss`, while a prose `Hold`,
   `Underweight` or `Sell` needs none and is accepted. No second rule is
   introduced; the validator is reused.

8. **The REVIEW is recorded everywhere.** The node publishes
   `final_rating` + `decision_review_reasons`; the state log, the Markdown
   header (`- Review reasons:`), the HTML header (`span.rating` = `REVIEW`), the
   CLI notice and the memory entry all reflect the same decision. The **final
   decision region itself** — CLI `V. Portfolio Manager Decision` panel, Markdown
   `## V. Portfolio Manager Decision`, and the HTML body — renders a single
   REVIEW summary (`reporting.py::decision_display_text`) that names the reasons,
   never the model's superseded `Rating: Buy` line or its entry instructions.
   The reconciliation is applied on read, so a state saved by an earlier version
   whose decision text still carries the old rating is also shown as the REVIEW
   summary.

## Consequences

- Adding `entry_price`/`stop_loss` as `Any` means callers that build a
  `PortfolioDecision` without prices keep working (both default `None`); a Buy
  or Overweight without valid prices is REVIEW, which is the intended contract.
- The free-text path can supply a uniquely identifiable rating only; a Hold,
  Underweight or Sell may pass with no prices, while a prose-only Buy/Overweight
  is REVIEW.
- The price contract strengthens the registry's earlier "finite numbers" wording
  to "finite, strictly positive"; the registry and trace matrix carry the change.
- The JSON-mode binding now requests `include_raw=True` so the raw body is
  available for the strict-decode check; the extra field is consumed internally
  and never reaches the decision model.

## History

- **Post-PR #52 corrections.** The slice landed in PR #52 left three defects that
  the original tests did not catch, because they replaced the model response
  boundary with string replies rather than the provider's parsed value:
  1. a prose-only Buy/Overweight was adopted (the free-text path never ran the
     price policy) — fixed by §7;
  2. a bare `NaN`/`Infinity`/`-Infinity` in a real JSON-mode response was parsed
     by LangChain into a `float('nan')` and misread as a supplied `invalid_*`
     price instead of a decode miss — fixed by §6 (raw-response-layer check);
  3. a top-level REVIEW still rendered the model's `Rating: Buy` and entry
     instructions in the report/CLI decision region — fixed by §8 (one REVIEW
     summary, reconciled on read).
  Regression tests: `test/offline/test_fr004_regression.py`. These clarify, and
  do not change, the contract above; the requirements registry is unchanged.

## Reopen conditions

- A vendor adds an exact-decimal or tick-size price contract.
- A decision format needs a price field this policy does not cover (e.g. a
  trailing stop), which would need its own reason code and approval.
