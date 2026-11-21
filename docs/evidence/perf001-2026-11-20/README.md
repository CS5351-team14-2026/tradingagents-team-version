# PERF-001 uncapped real trial — 2026-11-20

Status: **STOPPED / incomplete experiment**, not formal acceptance.

The plan was three fixed stock/date cases, two configurations and three
repetitions per case (18 analyses). Only the first AAPL/2026-11-13 pair completed.
The next AAPL baseline attempt was interrupted with human authorization. Do not
interpret the planned 18 analyses in manifest.json as completed measurements.

Real DeepSeek `deepseek-flash` in both tiers, temperature 0, max_tokens=None;
current default configuration versus public Quick profile. Each run has fresh
private memory/cache/results, checkpoints disabled. Timing includes graph
construction, analysis and normal persistence, excluding export. No historical
code version was executed. Provider/network latency is an external variable.

`uncapped-partial.json` is the original first-pair measurement, preserved without
retrofitting the new exporter schema. Baseline: 723.51 seconds / 24 observed LLM
calls; Quick: 310.70 seconds / 18 calls. These are two individual execution times,
not repeated medians or evidence that PERF-001 has passed. Token usage was partial;
complete token totals and costs are unavailable.

`uncapped-acceptance-diagnostics.json` captures the public state acceptance result:
**both reports REJECTED**, reasons NO_CLAIM_METADATA and PM_FREETEXT_FALLBACK.
Baseline also returned REVIEW due to missing_entry_price / missing_stop_loss.
The old export's `completed` means graph execution returned, not report acceptance.

The human approved stopping and using a common 8192-output-token cap next, then
requested code fixes and one smoke pair at a time. New capped samples must stay
separate from this uncapped trial. Threshold remains TBD. Inputs, source/dependency
fingerprints and the stop record are retained; private full reports and secrets
are excluded from this evidence directory.
