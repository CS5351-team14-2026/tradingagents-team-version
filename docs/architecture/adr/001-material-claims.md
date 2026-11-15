# ADR-001 — Material claims in the final recommendation

- **Status:** Approved (2026-11-15)
- **Deciders:** human reviewer (session approval)
- **Traces:** REQ-TA-FR-005, REQ-TA-QR-002, REQ-TA-INV-005
- **Context requirements:** REQ-TA-FR-004 and REQ-TA-INV-001 (rating semantics
  stay with those entries; this ADR does not change them)
- **Scope of this slice:** local vertical slice only. No run-path downgrade is
  activated (see §4).

## 1. Decision — what counts as a material claim

A **material claim** is exactly one item in the final recommendation's
structured **supporting-factor list** or **opposing-factor list**. The lists are
fixed at **three supporting and three opposing claims** per recommendation.
Everything else in the report (analyst reports, research/trading/risk sections,
the executive summary and investment-thesis prose) is narrative and is not a
material claim for this ADR.

Rationale: QR-002 measures a fraction of *formally defined* claims, and INV-005
needs a deterministic set to check. A closed, schema-backed list makes both
possible without an NLP classifier. Option A was chosen over rule-based prose
detection (unstable boundaries) and over claim-keying every report section
(unbounded token and audit cost).

## 2. Decision — how a claim carries its source

Each claim carries:

| Field | Meaning |
|---|---|
| `text` | The claim itself, one statement. |
| `source_id` | An artifact key from the report's existing `_SECTIONS` table (`market_report`, `sentiment_report`, `news_report`, `fundamentals_report`, `investment_debate_state.bull_history`, `investment_debate_state.bear_history`, `investment_plan`, `trader_investment_plan`, `risk_debate_state.{aggressive,conservative,neutral}_history`). |
| `observation_date` | `YYYY-MM-DD`; required when the claim asserts market data (currently the `market_report` source). |

The **producing agent is derived from `source_id`** by the checker using
`_SECTIONS`; it is never self-reported by the model. The `source_id` is the
identity: aliases, URLs or free-text citations are not accepted. The audit
treats `source_id` as resolvable only when the artifact is in the vocabulary
**and** the run actually contains a non-empty value at that state path.

The Portfolio Manager fills these fields in its existing structured-output call;
there is no extra LLM call and no post-hoc extraction pass.

## 3. Decision — acceptance rule

The pure checker `audit_material_claims(final_state)` returns a `ClaimAudit`:

- `ACCEPTED` — every material claim resolves to a non-empty artifact, every
  market-data claim carries a valid observation date no later than the analysis
  date, at most three claims per side, at least one claim cites an analyst
  report, and at least one attributed claim carries a dated observation.
- `DOWNGRADED` — one or more of those checks fail. Unresolvable claims are
  labelled `UNSUPPORTED` and stay visible; nothing is silently dropped. Reason
  codes are machine-readable.
- `NOT_ASSESSED` / `NO_CLAIM_METADATA` — the run has no claim metadata at all.
  This is **not** acceptance.

Reason codes: `NO_CLAIM_METADATA`, `UNTRACEABLE_CLAIM`, `UNKNOWN_SOURCE`,
`INVALID_CLAIM`, `CLAIM_LIMIT_EXCEEDED`, `UNDATED_MARKET_DATA`,
`INVALID_OBSERVATION_DATE`, `NO_ANALYST_REFERENCE`, `NO_DATED_OBSERVATION`.

This status is a **report-level traceability status**, not a rating. It does not
change `final_rating`, the REVIEW rule (REQ-TA-INV-001) or the validation gate
(REQ-TA-FR-004).

## 4. Deferred — fail-closed is not activated in this slice

The audit is now recorded: `record_decision` runs `audit_material_claims` before
`_log_state`, and the state log carries `claim_audit` (status, reasons, counts,
per-claim resolution). The checker is also tested offline, and `material_claims`
/ `claim_audit` are declared in `AgentState`. A decision without claims reports
`NOT_ASSESSED` (never `ACCEPTED`).

Run acceptance is still **not** gated on the audit. `claim_enforcement` is a
reserved boolean (default `False`, env `TRADINGAGENTS_CLAIM_ENFORCEMENT`); no
behaviour branches on it yet. A `DOWNGRADED` or `NOT_ASSESSED` audit does not
change `final_rating`, the memory-log entry, or report rendering. Activating
fail-closed — gating run acceptance on the audit and mapping the status onto the
REQ-TA-FR-006 run-status enum — is a later change.

## 5. QR-002 threshold — remains TBD

No attribution percentage is set by this ADR. The baseline attribution fraction
must first be measured per `docs/req/requirement-candidates.md` §8 row 3 (a
fixed sample of N reports from defined cases), recorded, and only then may an
accepted-result rule entry replace `TBD` in `docs/req/requirements.yaml`.
Until that measurement is recorded, the threshold is **TBD**.

## 6. Token cost

Claim fields ride in the existing Portfolio Manager structured-output call, so
there is no extra call. Added output is bounded by the six claims (text plus one
source identifier and, for market data, one date). No numeric token budget is
asserted here; token accounting belongs to REQ-TA-COST-001 and must be measured,
not assumed.

## 7. Reopen conditions

1. The §8 row-3 baseline attribution measurement is recorded → confirm or revise
   the accepted-result rule.
2. REQ-TA-FR-003 structured debate lands → decide whether debate evidence becomes
   a first-class source type.
3. REQ-TA-FR-006 statuses land → replace the report-level status with the run
   status and activate fail-closed through that gate.
4. The free-text Portfolio Manager fallback is exercised in a real run.
5. The sampled human claim audit shows the definition misclassifies principal
   reasons → reopen Option A vs prose detection.
6. A measured token-overhead threshold is approved and exceeded.
7. A structured-output provider rejects the added fields.
8. The `_SECTIONS` artifact vocabulary changes.

## 8. Consequences

- The structured Portfolio Manager call gains two bounded lists; existing
  fixtures remain valid because both lists default to empty.
- Reports gain an evidence ledger and the "not investment advice" notice.
- INV-005 is checkable offline as a pure function; run-level enforcement is
  explicitly deferred.
