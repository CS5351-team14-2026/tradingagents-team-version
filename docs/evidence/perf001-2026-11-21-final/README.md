# FR-007 / PERF-001 — final real evidence, 2026-11-21

18/18 analyses completed: AAPL, NVDA, MSFT at 2026-11-13; three repeats of each
configuration. This is real DeepSeek `deepseek-flash`, both tiers, temperature 0,
same vendors, sequential paired execution with alternating order and fresh
memory/cache/results per attempt. No whole-run token budget; checkpoints disabled.

**Protocol qualification:** both sides have the human-approved common per-output
8192-token cap. The baseline has no profile but is **not the entirely untouched
uncapped default** in Issue #62's example. Team review must accept this disclosed
experimental control; the files cannot be used to claim an uncapped-default result.

| Case | Baseline median (min–max), s | Quick median (min–max), s | Runtime reduction | N |
| --- | ---: | ---: | ---: | --- |
| AAPL | 396.86 (395.28–459.62) | 310.61 (300.54–350.87) | 21.73% | 3 + 3 |
| NVDA | 417.79 (383.23–444.13) | 323.48 (321.29–337.13) | 22.57% | 3 + 3 |
| MSFT | 435.81 (367.92–452.29) | 334.14 (302.59–377.35) | 23.33% | 3 + 3 |

Across nine paired completed runs per side: median baseline **417.79 s**,
Quick **323.48 s**; ratio-of-medians runtime reduction **22.57%**.
Complete paired token medians: **250148 → 121032**,
reduction **51.62%**. Median of the individual paired runtime reductions is
23.66%; this is a different statistic.
Report the actual signs; negative values mean slower/more tokens.

Report claim acceptance: **15/18 ACCEPTED**, remaining statuses
`{"REJECTED": 3, "ACCEPTED": 15}`; reasons `{"UNDATED_MARKET_DATA": 3, "NO_DATED_OBSERVATION": 3, "NO_ANALYST_REFERENCE": 1}`.
A completed graph is not necessarily an accepted investment report. Rejected
reports are retained, never re-run until favorable. These timings measure execution,
not financial accuracy or guaranteed production quality/latency.

As a descriptive sensitivity check, the six pairs where **both** report audits
are ACCEPTED have runtime medians 416.33 s → 315.95 s (24.11% reduction).
This selected subset does not replace the full fixed-case cohort or supply three
accepted repetitions per case; see accepted-pairs-sensitivity.json.

## Raw data and verification

- [comparison.json](comparison.json), [comparison.csv](comparison.csv): final selected
  paired measurements, settings, diagnostics and acceptance, without secrets.
- [attempt-history.json](attempt-history.json), [attempt-history.csv](attempt-history.csv):
  every attempt, including failures. 18 total attempts,
  0 failed execution attempts. Failed durations never become fast successes.
- [verification.json](verification.json): independent median/percentage/CSV checks;
  [canonical-metadata-check.json](canonical-metadata-check.json): all 18 report usage
  and typed-confidence records match evaluation. Source hashes still match.
- Inputs, resolved settings, source/dependency fingerprints, manifest and execution
  order document provenance. Prior source-cohort failures are in excluded-trials.json;
  old smoke/uncapped data is not pooled with this cohort.
- Local full offline preflight: **1905 passed**, 1 optional AWS dependency skipped,
  1 live test deselected, 100 subtests; full lint passed. Actual remote multi-Python
  CI and teammate approval are pending the user's manual PR.

`settings` and `diagnostics` in raw rows are JSON-encoded cells, consistently used
by JSON/CSV exports. Calls/tokens are provider observations for callback-visible
logical LLM calls; SDK-internal transport retries and provider billing may differ.
No price was configured, so cost remains unavailable; no fake billing estimate.
The public runner executed the real analyses; a final `compare --live --resume`
CLI verification reused all 18 records with **zero new model calls** and produced
identical JSON/CSV (see cli-resume-verification.json).
Typed confidence is preserved, with fallback absence unavailable. Per-call times
can overlap and must not be summed as wall-clock time.

## Acceptance and handoff

The measured medians are results, not previously approved targets. The strict
positive-reduction (>0%) minimum directly implied by the existing performance/
cost statements is proposed in threshold-proposal.json **for human PR adoption**.
Runtime meets that proposal: **True**; tokens meet it: **True**. Raw exports retain
their original measurement-time TBD target fields. COST-001 remains candidate/wont;
measurements do not silently change its ownership or implementation status.

Evidence addresses Issue #62; it does not automatically close the issue, approve
investment reports, approve a target, or bypass human-only rules/PR gates. Detailed
session logs and private full reports stay in the sibling local log folder.
