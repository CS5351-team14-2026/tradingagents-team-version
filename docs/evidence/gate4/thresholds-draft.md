# Gate 4 threshold draft (TBD — pending team review)

All values below are **TBD**. They are recorded so the team can review and set
them in one place; nothing in this draft blocks a merge. The gate currently
labels findings `FAIL` / `REVIEW` / `INFRASTRUCTURE_ERROR` with the *intent* that
`FAIL` and `INFRASTRUCTURE_ERROR` will block once the thresholds are approved;
until then the CI job is advisory (not a required check).

## Per-run hard rules (proposed blocking once approved)

| Code | Condition | Proposed action | Threshold |
|---|---|---|---|
| `UNFOUNDED_MARKET_DATE` | A market claim dated when the source had no date | block merge | TBD (currently a boolean signal) |
| `UNRESOLVABLE_SOURCE` | The audit reported `UNKNOWN_SOURCE` | block merge | TBD (currently zero-tolerance) |
| `EMPTY_REPORT` / missing fields | Incomplete run record | block (infra) | TBD |
| `INFRASTRUCTURE_ERROR` | Missing credential, unsupported provider, evaluation exception | block (infra) | TBD |

## Aggregate rules (proposed observation-only first)

| Metric | Definition | Threshold |
|---|---|---|
| acceptance rate | share of runs `ACCEPTED` | TBD |
| attribution rate | `claims_attributed / claims_total` | TBD |
| unfounded-date rate | share of runs with `UNFOUNDED_MARKET_DATE` | TBD |
| unknown-source rate | share of runs with `UNRESOLVABLE_SOURCE` | TBD |
| retry rate | share of runs needing the JSON-mode retry | TBD |

## Baseline observation (from `2026-11-22/baseline/baseline.json`)

- 9 runs, 0 infrastructure errors.
- 3 of 9 runs carry a hard defect the proposed rules would block: one
  `UNFOUNDED_MARKET_DATE` (a 2026-06-19 date absent from the undated market
  report) and two `UNRESOLVABLE_SOURCE`.
- 2 runs are missing-date-only (`REVIEW` observation).

These are inputs to the threshold discussion, not values.

## Fixed case set

- `test/fixtures/gate4/pm_cases.json` — offline audit behaviour cases.
- `test/fixtures/gate4/baseline_cases.json` — real-model baseline inputs
  (full dated evidence; market report without dates; partial reports).
