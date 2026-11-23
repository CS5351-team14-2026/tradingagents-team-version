# Gate 4 — Phase 3A formal baseline (real model, 3 cases × 3 runs)

- Date: 2026-11-22
- Provider: `deepseek`; Model: `deepseek-flash`
- Temperature: `unset` (the CLI has no temperature flag; the effective config is
  recorded as-is)
- Endpoint: provider default base URL (`https://api.deepseek.com`), no override.
- Credential: read from the environment (`DEEPSEEK_API_KEY`); never recorded.
- Overall status: `OBSERVE` (thresholds **TBD**); exit `0`.

The archived `baseline.json` is a byte-for-byte copy of the run output
(SHA-256 `3fea2e51c032ae5df3ac14b45241e4e7c6c85ef31db347d12c441a8d62e073d9`,
verified with `diff` and `cmp`). It contains only safe fields: per-claim source,
normalised observation date, attribution result and reason codes — no raw claim
text, prompt, endpoint or credential.

## Totals

- 9 runs (3 cases × 3 repetitions), **0 infrastructure errors**.
- Status is `OBSERVE` for every run; this is baseline measurement, not a verdict.

## Per-case audit distribution and claim attribution

| Case | Status counts | Attributed / total claims | Rating (per run) | Date-basis-unverified runs |
|---|---|---|---|---|
| `baseline_full_evidence_dated` | ACCEPTED ×3 | 18 / 18 | Overweight ×3 | 0 |
| `baseline_market_report_undated` | DOWNGRADED ×2, ACCEPTED ×1 | 14 / 18 | REVIEW, Overweight, REVIEW | 1 |
| `baseline_partial_reports` | DOWNGRADED ×2, ACCEPTED ×1 | 14 / 18 | Hold ×3 | 0 |

## Notable observation: fabricated date in the undated case

In `baseline_market_report_undated`, **run 2** was audited **ACCEPTED** (6/6
attributed), but the model dated its two `market_report` claims as
**`2026-06-19`**. That date appears nowhere in the input: the case's market
report deliberately carries no dates (only undated levels such as "about 2%",
"20-day", "50-day"). The audit accepted the claims because a supplied date is
currently self-consistent with the trade date, but the date has **no basis in
the source**. The run is correctly tagged `observation_notes: ["date basis
unverified"]`. This is the key finding the baseline was designed to surface: an
ACCEPTED audit does not, by itself, prove the date is grounded.

Runs 1 and 3 of the same case were DOWNGRADED (4/6 attributed) and rated REVIEW,
so the fabricated-date behaviour is intermittent, not systematic.

## Caveat on `matches_expectation`

These baseline cases carry no `expected_status`, so `matches_expectation` is
`false` for every run by construction. That is **not** a model failure; it only
means there is no preset answer to compare against. Failures would show as
`evaluator_exception` / `errors`, of which there are none.
