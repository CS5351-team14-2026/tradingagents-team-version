# ADR-007 — Paired evaluation and durable measurements

Status: proposed for team PR review. The human approved the implementation scope
and final real experiment on 2026-11-21; this document does not invent a teammate
approval or a numeric performance target.

Requirements: FR-007, PERF-001; integration contracts ADR-001 (claims), ADR-003
(prices/strict JSON), ADR-004 (shared usage), QR-004 (canonical run metadata).

## Decision and boundaries

- `evaluation.py`: typed, pure measurements, pair arithmetic and JSON/CSV export.
- `evaluation_runner.py`: public graph construction/propagation, timing, isolated
  per-attempt state, alternating execution order, safe callback diagnostics.
- `evaluation_checkpoint.py`: experiment identity and atomic durable observations.
- `cli/main.py::compare`: explicit `--live`, case/config validation and exports.

The graph remains the analysis engine. No rating/price/audit rules are disabled,
no prompt text is parsed to invent confidence, and no unknown token total becomes
zero. The graph's shared usage ledger is attached before report persistence.

## Experimental protocol

Pin provider, models, temperature, vendors, case/date and common output settings.
A named Quick profile changes only its approved analysts/round/tool mapping.
Use three fixed cases with three repeats per configuration, alternating order,
sequential measured runs, fresh private memory/cache/results and no token budget.
Time graph construction, propagation and normal persistence with a monotonic
clock. Exclude the experiment's journal/export I/O. Provider/network variation
remains an external limitation; report medians, spread, counts and all failures.

The human approved a common 8192-output-token cap after an uncapped trial ran too
long. It is an experimental control shared by both sides, not an entire-run token
budget. Label this capped baseline explicitly; never pool it with uncapped data
or claim it exactly matches the untouched default configuration.

## Recovery and privacy

Persist each terminal run via fsync plus atomic publication before advancing.
Resume only when source and complete input/pricing/factory digests match. Cache
completed runs even when claim acceptance is REJECTED: retrying them until they
pass would select favorable outputs. A failed execution is retried only with the
explicit retry flag and uses fresh state; retain previous attempts and exports.
Concurrent directory ownership is exclusive. Never infer time for an interrupted
uncommitted measurement. No credentials, endpoints or local paths enter protocol
records; configuration is compared by digest. Detailed logs/private reports stay
outside the repository at the human's request.

## Alternatives and tradeoffs

- Pair-only persistence was simpler but lost a completed side on interruption;
  rejected after real connection failures made repeating paid work costly.
- Running experiments concurrently is faster but confounds wall-clock comparison;
  rejected for this measurement.
- Dropping extra claims, weakening audit, or omitting failed runs could make a
  cleaner result but violate ADR-001/INV-005 and measurement integrity; rejected.
- Adopting numeric targets before baseline measurement is forbidden. Measurement
  values and a proposed pass threshold are distinct; team review adopts targets.

## Verification and reopen conditions

Offline arithmetic/failure tests; real client binding with mocked HTTP; real
LangGraph with scripted providers; journal interruption, provenance mismatch and
explicit recovery tests. Full prior offline regression and lint must pass before
real measurement. Archived real JSON/CSV is the performance evidence, not a mock
benchmark. Reopen for a changed provider/model, threshold, source revision,
parallel execution policy or failure/retry policy; do not silently pool cohorts.
