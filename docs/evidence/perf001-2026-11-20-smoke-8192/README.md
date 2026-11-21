# PERF-001 common-cap smoke — 2026-11-20

Status: **SMOKE COMPLETED**, 2/2 graph executions completed, 2/2 claim audits
ACCEPTED; **formal PERF-001 acceptance NOT ASSESSED**.

One AAPL/2026-11-13 pair, baseline first then Quick. Both tiers use real
DeepSeek `deepseek-flash`, temperature 0 and the human-approved common
per-output `max_tokens=8192`. This is a common capped comparison, not the
unmodified default. Do not combine it with the separate uncapped trial.
Fresh private memory/cache/results per run; checkpoints disabled. Timing
includes graph construction, propagation and normal persistence; exports excluded.

| Configuration | Seconds | LLM calls | Input tokens | Output tokens | Total tokens | Claim audit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Capped baseline | 301.272794 | 18 | 177523 | 65286 | 242809 | ACCEPTED |
| Capped Quick | 270.360498 | 15 | 130569 | 49384 | 179953 | ACCEPTED |

Both callback token observations are complete. All 33 calls completed; no
provider-call error or output-length termination was observed. Longest single
call: baseline 61.51 seconds, Quick 53.72 seconds. Calls may overlap, so never
sum call timings as wall-clock time. Model/network latency and sequential agent
work account for substantial runtime even in this one-pair smoke.

Raw pair runtime reduction is 10.26%; this is descriptive, **not a repeated
performance estimate or an adopted threshold**. The two built-in claim audits
passed, with empty decision-review reasons. Baseline returned Underweight and
Quick Hold; passing the claim audit is not human approval of investment quality
or a guarantee that configurations yield identical recommendations. Cost and
confidence remain unavailable where not configured/reported, never fabricated.

`comparison.json` and `comparison.csv` contain the measurements, pair fields,
resolved allowlisted settings, acceptance and safe per-call diagnostics.
`manifest.json`, inputs, dependency versions and source hashes document conditions.
All source hashes still matched after execution.

Known integration finding: the private full-state report's canonical
run_settings.run_metadata still has null token and call fields, while the
comparison's real callback measurements are complete. The sanitized side-by-side
`canonical-metadata-check.json` preserves this distinction. The shared graph's
persisted metadata path needs follow-up with the QR-004 / FR-002 owners; this
change does not rewrite their graph, provider or accounting implementation, and
it does not turn null canonical values into zeros.

This smoke is insufficient for the registered repeated-case PERF-001 criterion.
Threshold remains TBD and target_verdict remains not_assessed. The next
experiment can be reviewed and run in small batches; it must preserve the same
protocol, retain every failure, alternate order and gather the agreed repetitions
before any formal performance conclusion. Detailed logs, API credentials and
private full reports stay outside this evidence directory.
