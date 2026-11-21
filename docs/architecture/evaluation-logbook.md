# Evaluation logbook

> Deliverable D2.9: index of the evidence accumulated behind the architecture
> choices, in chronological order. Raw artefacts live under `docs/evidence/`
> and in the AI-use log; this file records what each measurement concluded.

## 2026-11-13 — Claim-attribution baseline (ADR-001 §5)

- Apparatus: deepseek-flash for both tiers, three tickers (NVDA, 0700.HK, BABA).
- Result: 3/3 runs `ACCEPTED`, **18/18 material claims attributed**; a
  confidence-validation run on AAPL produced 6/6 `ACCEPTED` with
  `confidence = medium`.
- Conclusion: QR-002 could be written unconditionally (no percentage
  threshold); recorded in ADR-001 §5 and the registry fit criterion.

## 2026-11-13 → 11-17 — Fail-closed acceptance (ADR-001 §4)

- Unit/offline evidence: 13 test functions / 18 cases covering unknown source,
  undated market data, missing metadata, free-text fallback, rating isolation.
- Process evidence: reviewer feedback on a real NVDA run showed
  `NO_ANALYST_REFERENCE` as the only downgrade reason; the Portfolio Manager
  prompt was then given the analysts' own reports ("Primary analyst evidence")
  plus a minimum-one-direct-citation rule, with prompt tests.
- Conclusion: fail-closed activated with a three-value verdict; rating
  semantics untouched.

## 2026-11-20 — Comparison smoke (capped 8192)

- Apparatus: `docs/evidence/perf001-2026-11-20-smoke-8192/`; early smoke run
  to validate the comparison command end to end.
- Conclusion: tooling works; the full protocol was still needed.

## 2026-11-21 — Final paired comparison (FR-007 / PERF-001)

- Apparatus: `docs/evidence/perf001-2026-11-21-final/` — AAPL, NVDA, MSFT at
  2026-11-13; 3 repetitions × 2 configurations; real deepseek-flash both tiers;
  temperature 0; alternating order; fresh memory/cache/results per attempt;
  common per-output 8192-token cap on both sides; no whole-run budget.
- Result: **18/18 executions completed**; runtime median **417.79 s → 323.48 s
  (−22.57%)**; paired token medians **250 148 → 121 032 (−51.62%)**; median of
  per-pair runtime reductions 23.66% (a different statistic, reported
  separately).
- Acceptance: **15/18 ACCEPTED**, 3 `REJECTED` retained (reasons:
  `UNDATED_MARKET_DATA` ×3, `NO_DATED_OBSERVATION` ×3,
  `NO_ANALYST_REFERENCE` ×1) — rejected reports are kept, never re-run until
  favourable.
- Protocol qualification: the baseline is the capped no-profile configuration,
  not the untouched uncapped default; this was explicitly accepted in review
  and must accompany every quoted figure.
- Integrity: source digests and evidence checksums recorded (`SHA256SUMS.json`,
  `source-sha256.json`); the 354 SHA-256 checksums were baselined for the
  secret scan after entry-by-entry verification.

## 2026-11-21 — Secret-scan gate adoption (ADR-006)

- Apparatus: `detect-secrets==1.5.0`, pinned; PR-blocking job comparing
  against the base branch baseline; `.secrets.baseline` changes require the
  `secret-baseline-approved` label.
- Result: 371 baseline entries (17 pre-existing + 354 evidence checksums);
  independent re-scan reproduced the baseline entry-for-entry; zero unexplained
  findings.
- Conclusion: SEC-001 closed; the review recorded in the PR is the evidence.

## Process evidence (not measurements)

- `docs/ai-use-log.yaml` — every agent session, including the Codex-first
  FR-002 attempt and its OpenCode redo.
- `transcripts/**` — supervised session records with intervention indices.
- `docs/review-memo.md`, `docs/bug-diary.md`, `docs/debt-register.md` — review
  verdicts, defect history and known gaps.
- `docs/req/requirement-candidates.md` §8 — the measurement plan that
  preceded these experiments (threshold-first discipline).
