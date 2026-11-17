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
command rejects the ambiguous experiment). This local integration trial does not
replace the formal comparison after the FR-001 follow-up fix merges.

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
