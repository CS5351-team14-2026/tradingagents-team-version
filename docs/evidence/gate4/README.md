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

## Per-run REVIEW, workflow-level NOT_APPLICABLE, and aggregation

Three levels are kept distinct so a report is never misread:

**Per-run decision (each replay of each fixed case).** `PASS`, `REVIEW`, `FAIL`
or `INFRASTRUCTURE_ERROR`, as listed above. A `REVIEW` is a *reasoned, non-blocking
observation* — e.g. a thin-evidence case, or a market claim that simply omits a
date — and is always recorded with its reason code, never silently dropped. The
per-run report keeps the **PM decision** (`pm_decision`, the rating) separate from
the **evidence-audit** result (`audit_status` + `audit_reasons`), so a downgrade
caused by the audit is visible next to the rating it came with.

**Workflow-level NOT_APPLICABLE.** Before any model config or credential is read,
the trigger matcher decides whether the PR touches a tracked prompt/model/parsing
surface. A pure-docs PR is `NOT_APPLICABLE` at the workflow level: the gate does
not evaluate anything and never claims PASS for work it did not do.

**Aggregation into the final CI verdict (one of the four #81 statuses).**
1. Each case's runs are decided per-run, then collapsed to a case decision.
2. A case that declares `expects_pass` (the full-evidence case) must have **every**
   run PASS to *meet its acceptance*; if it does not, the whole group cannot be
   PASS.
3. Any run `FAIL` or `INFRASTRUCTURE_ERROR` makes the group `FAIL` /
   `INFRASTRUCTURE_ERROR` (most severe wins).
4. If no hard defect occurred and every full-evidence case met its acceptance, the
   group is `PASS`; otherwise a residual (acceptance-unmet but no hard defect) is
   `REVIEW`.
5. The four CI statuses are `PASS` / `FAIL` / `NOT_APPLICABLE` /
   `INFRASTRUCTURE_ERROR`. The group decision maps to CI **by cause**, not
   blanket:
   - group `REVIEW` **with the full-evidence case met** → CI `PASS` (exit 0); this
     is the "only thin cases carry a reasoned REVIEW" case, and the per-case
     `REVIEW` detail stays in the report;
   - group `REVIEW` **because the full-evidence case did NOT meet its acceptance**
     → CI `FAIL` (exit 1), reason `full_evidence_acceptance_unmet`, naming each
     unmet case and its run reasons. This must never be reported as `PASS`;
   - group `FAIL` / `INFRASTRUCTURE_ERROR` → same CI status (exit 1 / 2).
   Numeric pass-count / ratio thresholds remain a **draft**
   (`thresholds-draft.md`, `tools/ci/semantic_eval_thresholds.yaml`) pending
   independent review.

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
