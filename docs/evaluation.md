# Configuration comparison — FR-007 / PERF-001

The `compare` command measures the existing graph; it does not change any agent,
claim audit, rating rule, memory implementation or default analysis command.

Prepare three files. `cases.json` is a list of at least three objects:

```json
[
  {"ticker": "AAPL", "analysis_date": "2026-01-05"},
  {"ticker": "NVDA", "analysis_date": "2026-01-05"},
  {"ticker": "0700.HK", "analysis_date": "2026-01-05"}
]
```

`baseline.json` is a settings override object, e.g. `{"temperature": 0}`.
`enhanced.json` can change `analysts`, `max_debate_rounds`,
`max_risk_discuss_rounds`, `max_tool_rounds`, retaining the same temperature.
Both configurations resolve against the current application defaults; this is
configuration comparison, not execution of an older checkout. Save the resolved
allowlisted settings in the output as evidence.

For the FR-001 Quick integration, use `{"temperature": 0, "profile": "quick"}`
as enhanced.json, and `{"temperature": 0}` as baseline.json. The public
`resolve_profile` API applies the teammate-approved mapping; only fields explicitly
present in your JSON override that mapping. The graph receives `profile` and the
original explicit overrides, not an analyst list that would silently override Quick.
Unset TRADINGAGENTS_PROFILE when measuring a no-profile baseline (otherwise the
command rejects the ambiguous experiment). The final frozen-source formal comparison is now
[recorded here](evidence/perf001-2026-11-21-final/README.md); previous smoke and
interrupted source cohorts are excluded from its statistics.

```bash
tradingagents compare --cases cases.json --baseline baseline.json --enhanced enhanced.json --output comparison-run-01 --repetitions 3 --live
```

`--live` explicitly acknowledges provider calls and possible costs; without it
no files or providers are accessed. Three cases with three repetitions run the
graph 18 times. Configure credentials through the existing application mechanism,
never put them in the override JSON or generated reports.

The output directory must not exist. It contains `comparison.json`,
`comparison.csv`, and isolated per-run state/cache/memory directories. Each run
starts from empty private memory and cache, checkpoints disabled. Order alternates
between baseline-first and enhanced-first. Timing includes graph construction,
analysis and normal persistence, but excludes comparison export.

JSON includes paired successful medians, min/max spread, sample counts and failed
pair counts. CSV includes one raw row per run with pair percentages. Failed pairs
remain in raw data but cannot count as a speedup; report both successful and failed
sample counts. Missing/partial usage never becomes a complete zero total.
Confidence absent from state is unavailable rather than inferred from prose.

Optional `--input-price` and `--output-price` are explicit USD prices per million
tokens. The single-rate option requires the same provider and model in both tiers;
otherwise omit it and cost is unavailable. No prices are fetched or guessed.

Performance target remains TBD, with `target_verdict: not_assessed`, until actual
measurements and human target approval exist. Simulated tests are evidence of
implementation correctness, not an observed performance improvement. Real PERF-001
acceptance additionally requires the team's approved Quick implementation, fixed
provider/models/temperature/vendors/network, repeated cases and archived raw data.

Implementation uses public graph construction/propagate and callback APIs.
`evaluation.py` owns pure records, comparison, aggregation and export;
`evaluation_runner.py` owns evaluation execution and observation. CLI adds one
subcommand. No original backtest or analysis behavior is replaced.

## Smoke before a repeated experiment

For a live diagnostic, give `cases.json` exactly one stock/date and add `--smoke`:

```bash
tradingagents compare --cases cases.json --baseline baseline.json --enhanced enhanced.json --output smoke-01 --smoke --live
```

This always runs **two analyses** (one baseline, one Quick), regardless of
`--repetitions`. It still calls every agent selected by each configuration;
“smoke” does not mean one API call or an instant result. Progress events identify
run starts/ends and model starts/ends/errors. Each call's elapsed time,
usage status, safe error type/HTTP status and termination reason (when reported)
are exported under `diagnostics`. Parallel call durations must not be summed
as end-to-end wall time. Raw exception text and model content are excluded.

For the human-approved diagnostic protocol, use `{"temperature":0,"max_tokens":8192}`
for baseline and `{"temperature":0,"max_tokens":8192,"profile":"quick"}` for Quick.
The cap applies per model output, not to the whole graph; it does not bound
network time. This is a **common capped configuration comparison**, not the
unmodified default. Never combine these samples with uncapped samples.

`experiment.json` identifies smoke versus repeated comparison. A smoke cannot
establish PERF-001's repeatability or a performance threshold. Inspect
`acceptance_status` / `acceptance_reasons` separately from execution `status`:
a completed graph may return a REJECTED report or a REVIEW decision. Pair timings
remain descriptive execution measurements, and `accepted_report_pairs` counts
only completed pairs whose two claim audits returned ACCEPTED. It does not
certify the investment recommendation. Missing, contradictory, failed or partial
usage remains incomplete, using the team's public `normalize_usage` contract.

## Durable progress and explicit recovery (FR-007)

Every terminal run is atomically stored under `measurements/` before the next
run starts. `protocol.json` contains only source/input digests: paths and endpoint
URLs are not exposed. The original comparison and claim audit semantics remain
unchanged. The CLI now supports:

```bash
tradingagents compare --cases cases.json --baseline baseline.json --enhanced enhanced.json --output comparison-run-01 --repetitions 3 --live --resume
```

Resume requires identical source, full configuration, cases, repetitions,
provider/models, pricing and factory identity. Mismatches fail before provider
calls. Completed runs, including completed REJECTED reports, are never re-run to
obtain a more favorable result. A known execution failure is returned as a failure
unless the human also supplies `--retry-failed`; that flag retries only failed
runs, with fresh private state. Every previous attempt remains in `measurements/`,
and earlier exports move to `export-history/`. Interrupted runs whose measurement
was not committed must be completed again; no elapsed time is reconstructed or
invented. A directory lock prevents simultaneous paid resumes.

When publishing a resumed experiment, retain **all attempt records**, failure
counts, and the final paired JSON/CSV. Never present a recovered dataset as if
no attempts failed. Do not pool measurements from changed source/protocols.

Integration fixes grounded in the real trial: JSON-mode PM retry explicitly
requests JSON with the existing decision schema; supporting/opposing output
schemas cap each list at the already-approved three claims (ADR-001), without
trimming claims or relaxing audit/price/strict-NaN rules. Direct graph calls now
use the shared usage handler and attach its observation before state persistence;
CLI-owned ledgers are reused. Typed PM confidence is exposed directly to the
comparison; free-text fallback confidence remains unavailable.

## Recorded final experiment

See [18-run raw evidence](evidence/perf001-2026-11-21-final/README.md). Across 9 completed paired runs/configuration: median runtime 417.79s -> 323.48s (22.57% reduction); median complete paired tokens 250148 -> 121032 (51.62%). Report claim acceptance 15/18; failed execution attempts 0. The common 8192 cap, prior failed trials, every attempt, spread and human target/protocol adoption are explicitly documented.

## Integration reconciliation after the measured cohort

The 18-run archive above belongs to the source fingerprints recorded at measurement
time, before the subsequent integration merge (local evidence commit `b32a840`).
The archived JSON/CSV and fingerprints remain unchanged; they are not measurements
of the newly merged revision. The merge is checked by offline regression only.
No new paid experiment was started to resolve merge conflicts.

ADR-005 / QR-001 now returns some failures as `(state, REVIEW)` without raising.
The comparison adapter therefore checks the public `run_settings().run_metadata`
lifecycle/failure block and returned `run_failure`, marks such measurements as
failed for comparison, and excludes their pair from speedup statistics. This also
excludes graceful degradation carrying an explicit failure block even if the graph
lifecycle is completed. A rejected claim audit or REVIEW rating **alone** remains
separate and does not invent an execution failure. Raw attempts and observed usage
are retained; raw provider diagnostics are not copied. ADR-007 describes evaluation
and recovery; the team's ADR-005 and ADR-006 keep their existing meanings.
