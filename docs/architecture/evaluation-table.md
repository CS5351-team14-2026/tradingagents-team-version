# Candidate evaluation table

> Deliverable D2.8: the comparison that justifies the chosen architecture.
> Each row: the decision, the options considered, what was chosen, why, and the
> condition that would reopen it. ADR references hold the full argument.

| # | Decision | Options considered | Chosen | Why | Reopen trigger |
| --- | --- | --- | --- | --- | --- |
| 1 | Cost control lever | (a) keep the independent env knobs; (b) named profile resolving to a settings set; (c) one CLI command per profile | **(b)** ADR-002 | One named control for analyst set + three round budgets; invalid profile fails before any LLM call; unset reproduces v0.7.1 exactly; explicit settings override per field | A profile mapping that cannot be expressed as static settings (e.g. adaptive rounds) |
| 2 | Budget enforcement point | (a) CLI-only counter (baseline); (b) graph-level ledger admitting optional calls; (c) cancel in-flight provider requests | **(b)** ADR-004 | API callers get the same ceiling; cancellation is not offered reliably by providers, so no exact hard cap is claimed | A provider exposes cancellable requests with usage guarantees |
| 3 | Final-decision contract | (a) free text + regex rating (baseline); (b) structured output + deterministic validation with REVIEW fallback; (c) LLM self-check | **(b)** ADR-003 | Machine-checkable prices/rating; REVIEW on any miss; LLM self-check is non-deterministic and cannot be a gate | A provider cannot do structured output at all |
| 4 | Claim traceability mechanism | (a) prose citations; (b) structured claims with `source_id` + observation date + deterministic audit; (c) LLM-as-judge | **(b)** ADR-001 | Auditable offline, zero-tolerance testable, no extra model calls; prose and judging are not machine-checkable | A claim type appears that cannot be tied to a report artefact |
| 5 | Acceptance rule | (a) record the audit only (deferred); (b) gate acceptance, three-value verdict; (c) force the rating to REVIEW on failure | **(b)** ADR-001 §4/§5 | Rejection must not touch rating semantics (INV-001 owns those); `NOT_ENFORCED` keeps the disabled path honest | A downstream consumer needs a single run-status enum (FR-006) |
| 6 | Failure handling | (a) let exceptions escape (baseline); (b) controlled failure codes + REVIEW + safe diagnostics; (c) unlimited retries | **(b)** ADR-005 | Bounded latency, machine-readable record, no fabricated recommendation; unlimited retry is unbounded latency | A new failure class needs a code (extend the enum) |
| 7 | Secret protection | (a) ad-hoc scrubbing (baseline); (b) redaction at output boundaries + PR-blocking scan with reviewed baseline; (c) scan only | **(b)** ADR-006 | Runtime logs and reports are covered too; the label + base-baseline comparison prevents silent re-baselining | A secret type the detector cannot see (then extend detection) |
| 8 | Performance evidence | (a) backtest grid scoring (baseline); (b) paired comparison with frozen sources and committed evidence; (c) single-run timing | **(b)** ADR-007 | Paired, repeated, alternating order, frozen source digests; single runs cannot separate signal from noise | The measurement is needed under a different cap or provider |
| 9 | Prompt governance | (a) extract every prompt into files; (b) keep prompts inline, commit versioned snapshots under `prompts/`; (c) no versioning | **(b)** | Extracting all prompts is a large risky refactor late in the project; snapshots give the evaluation gate a stable target | Prompt edits become frequent enough to need file-level diffing |
| 10 | Structured Bull/Bear debate (FR-003) | (a) schema per debate round; (b) keep free text and rely on the final-decision contract | **(b) — not pursued** | Cost/benefit at this stage: the decision contract (row 3) already bounds the output; debate structure would add tokens without a verified consumer | A consumer of per-round structure appears |
| 11 | Run-status enum (FR-006) | (a) implement the four-value enum; (b) carry the acceptance verdict instead | **(b)** | FR-006 was dropped (`wont`); the acceptance verdict already answers "can this report be trusted" without inventing a second status vocabulary | A status consumer outside the report appears |
| 12 | Multi-agent topology | (a) keep the existing analyst/debate/manager graph; (b) add agents; (c) collapse to a single agent | **(a)** | Adding agents multiplies coordination cost and tokens (SA: multi-agent is a cost); collapsing would discard verified behaviour | A driver requires isolation or parallel exploration |

## Cost/quality tradeoff statement (MoSCoW)

`must` items (profiles, budget, decision validation, claim traceability,
comparison, reliability, offline testability, secret safety, three invariants)
were delivered. `wont` items (structured debate, run-status enum, cost target,
governance family GOV-001..005) were dropped to keep the critical path
deliverable within the project window; their rationale and reopen conditions
are in `docs/architecture/option-ledger.md`.
