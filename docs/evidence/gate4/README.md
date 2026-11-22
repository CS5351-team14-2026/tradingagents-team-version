# Gate 4 — Semantic Evaluation Gate (Portfolio Manager first version)

Course gate 4 (project.pdf p10): a prompt/model change is evaluated against fixed
inputs before it can merge. This directory holds the evidence and the design of
the gate. Thresholds are **TBD** until the team reviews them
(`thresholds-draft.md`); until then the gate **observes** and does not block.

## What it evaluates

Per run, the Portfolio Manager's `material_claims` are scored by the existing
deterministic claim audit (`tradingagents.reporting.audit_material_claims`). The
gate then classifies each run:

- `PASS` — every claim attributed to a real source with grounded dates.
- `REVIEW` — thin evidence or a missing-date-only run with no hard defect
  (observation; does not block).
- `FAIL` — a hard defect: `UNFOUNDED_MARKET_DATE` (a market claim dated with a
  date absent from the source) or `UNRESOLVABLE_SOURCE` (the audit reported
  `UNKNOWN_SOURCE`).
- `INFRASTRUCTURE_ERROR` — the run/report could not be judged (empty report,
  missing fields, evaluator exception, missing credential, unsupported model).

Top-level CI status is one of the four #81 statuses: `PASS` / `FAIL` /
`NOT_APPLICABLE` / `INFRASTRUCTURE_ERROR`. An all-REVIEW result maps to top-level
`PASS` (no hard defect) with the per-run `REVIEW` detail preserved.

## Layout

| Path | Purpose |
|---|---|
| `2026-11-22/smoke/valid_dated_claim/` | First real-model single-case smoke (redacted). |
| `2026-11-22/baseline/` | Formal baseline: 3 cases × 3 runs, `baseline.json` + README. |
| `thresholds-draft.md` | Threshold proposal (all TBD pending review). |
| `delivery-files.md` | Complete file list for this deliverable. |

## How the model is chosen

The gate keeps **no model whitelist** and hard-codes no provider. It reuses the
application's own deep-tier resolution (`llm_clients.factory.tier_provider` +
`build_llm_kwargs` + `create_tier_client`), so the provider, model, temperature
and provider-specific reasoning settings that govern the Portfolio Manager are
exactly those the candidate version would use.

- **Formal PR check (CI):** uses the candidate's actual deep-tier config
  (`TRADINGAGENTS_*` / `DEFAULT_CONFIG`). If a PR switches the PM model, the gate
  evaluates the **new** model. The report records the effective non-sensitive
  config and the candidate commit SHA.
- **Manual / smoke runs:** may pin a model explicitly via env
  (`GATE4_PROVIDER`, `GATE4_MODEL`, `GATE4_TEMPERATURE`); the report is then
  marked `config_overridden: true`. The DeepSeek `deepseek-flash` smoke and the
  9-run baseline were produced this way and are preserved unchanged.
- **Failure, never fallback:** an unsupported provider, missing model id, or a
  missing credential returns `INFRASTRUCTURE_ERROR` with a fixed reason
  (`unsupported_provider` / `missing_model` / `missing_credential`); the gate does
  not silently switch to another model.
- **Credential boundary:** docs-only PRs return `NOT_APPLICABLE` before any
  config or credential access. The live call runs only in the trusted execution
  environment (the CI job with the selected provider's secret, or the owner's
  machine) and takes only that provider's credential from the environment. No API
  key appears in code, reports, logs or transcripts.

## Code

- `tools/sem_eval/{triggers,replay,replay_cli,gate,ci_entry,reportgen,ci_*}.py`
- `.github/workflows/gate4-semantic-eval.yml` (non-required check; secret-gated
  live path).
