# Gate 4 delivery file list

Complete file list for the Gate 4 (Portfolio Manager semantic-evaluation) work.
Existing `ci.yml`, application source under `src/`, the archived baseline
evidence, and teammate records are **unchanged**.

## Tooling (`tools/sem_eval/`)

| File | Role |
|---|---|
| `__init__.py` | Package exports. |
| `evaluator.py` | Offline pre-check evaluator (PASS/FAIL/NOT_APPLICABLE/INFRASTRUCTURE_ERROR, exit 0/1/2). |
| `cli.py` | Offline pre-check CLI (`result.json` + `summary.txt`). |
| `triggers.py` | Reusable trigger matcher (docs → NOT_APPLICABLE; prompt/model → evaluate). |
| `replay.py` | PM replay adapter: production node + double seam; `run_baseline` (N runs), per-claim safe report, observation notes. |
| `replay_cli.py` | Single-case replay entry (explicit provider/model; key from env). |
| `gate.py` | Gate decisions: PASS / REVIEW / FAIL / INFRASTRUCTURE_ERROR; REVIEW→observe; empty/missing → infra. Formal CI enforces the fixed 3-case × 3-run set; completeness and run-number errors → INFRASTRUCTURE_ERROR. Per-run provenance keeps the model's own rating, the app-validated rating + reasons, and the audit result distinct. |
| `ci_entry.py` | `evaluate_pr`: triggers → gate → four-status CI result. Group REVIEW maps to PASS only when the full-evidence case meets its acceptance; a thin-evidence REVIEW is a non-blocking observation. A report missing required cases or run records → INFRASTRUCTURE_ERROR. |
| `reportgen.py` | Current-PR report: candidate SHA, case version, effective PM model config (provider/model/temperature/reasoning from the app's own resolution; no whitelist), per-case results, verdict, failed rules; `report.json` + `summary.txt`. `candidate_llm_factory` builds the deep-tier client from the candidate config. |
| `ci_trigger_main.py` | CI helper: compute trigger verdict. |
| `ci_decide_main.py` | CI helper: NOT_APPLICABLE (docs, no config/cred) / INFRASTRUCTURE_ERROR (no cred, unsupported cfg — no fallback) / live report + gate from the candidate config. Manual runs may pin `GATE4_PROVIDER`/`GATE4_MODEL`/`GATE4_TEMPERATURE` (marked `config_overridden`). |

## Workflow

| File | Role |
|---|---|
| `.github/workflows/gate4-semantic-eval.yml` | Non-required advisory job. Draft-PR `pull_request` job injects **no** model credential (trigger + offline gate only; a triggered PR reports INFRASTRUCTURE_ERROR). The live replay runs separately in a trusted environment with only the candidate provider's credential. Uploads `gate4-report/{report.json,summary.txt}`. |

## Fixtures

| File | Role |
|---|---|
| `test/fixtures/gate4/pm_cases.json` | Offline audit behaviour cases. |
| `test/fixtures/gate4/baseline_cases.json` | Real-model baseline inputs (3 distinct). |

## Tests (offline; no network, no real model)

| File | Count |
|---|---|
| `test/offline/test_sem_eval_gate4.py` | offline pre-check |
| `test/offline/test_sem_eval_replay.py` | replay adapter |
| `test/offline/test_sem_eval_replay_cli.py` | single-case entry |
| `test/offline/test_sem_eval_baseline.py` | baseline repetition + per-claim report |
| `test/offline/test_sem_eval_gate_rules.py` | gate decisions |
| `test/offline/test_sem_eval_ci_entry.py` | CI adapter + reportgen + helpers |
| `test/offline/test_sem_eval_review_fixes.py` | source-supported dates + acceptance gating |
| `test/offline/test_sem_eval_completeness.py` | formal-CI completeness (3×3 set, run numbers, expects_pass; problems in report.json + summary) |
| `test/offline/test_sem_eval_rating_provenance.py` | rating provenance (model vs validated vs audit; Buy→REVIEW, unknown, historical) |

## Evidence

| File | Role |
|---|---|
| `docs/evidence/gate4/README.md` | Gate 4 overview. |
| `tools/ci/semantic_eval_thresholds.yaml` | Canonical #81 threshold draft (all TBD; hard rules + aggregate metrics + case set). |
| `docs/evidence/gate4/thresholds-draft.md` | Human-readable threshold proposal (all TBD). |
| `docs/evidence/gate4/delivery-files.md` | This list. |
| `docs/evidence/gate4/2026-11-22/smoke/valid_dated_claim/{result.json,summary.txt,README.md}` | First real-model smoke. |
| `docs/evidence/gate4/2026-11-22/baseline/{baseline.json,README.md}` | Formal baseline (3×3). |

## Records

| File | Role |
|---|---|
| `docs/ai-use-log.yaml` | Session entries (Phase 1 committed; later phases tracked in the transcript). |
| `transcripts/60704848-WuYu.md` | Personal transcript (all Gate 4 phases appended). |
