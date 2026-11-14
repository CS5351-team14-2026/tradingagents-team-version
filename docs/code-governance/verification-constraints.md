# Verification constraints — rules the verification layer applies (deliverable D4)

## VC-1 — Coverage rules

1. Every requirement `fit_criterion` has at least one automated test.
2. Every invariant has at least one negative test that **fails when the
   invariant is violated**.
3. Every test cites the requirement/invariant ID it verifies (docstring or
   test name), e.g. `test_offline_profiles_apply_mapping[REQ-TA-FR-001]`.
4. Every round of new work runs **all previous rounds' suites** with zero
   regressions (course gate 5).

## VC-2 — Three verification layers (project.pdf p6)

| Layer | What | Mechanism today |
|---|---|---|
| Structural | imports, module boundaries, permissions, architecture fitness | `ruff check .` (strict, full repo); schema gate on the registry; permission fitness function planned (DEBT-006); safe-path checks planned (DEBT-004) |
| Regression | all previous suites pass | `pytest -q` full offline suite per PR, matrix py3.11–3.14 (+TZ); required context in branch protection |
| Behavioural | quality thresholds (faithfulness/relevance-style scores, zero safety escapes) | fit-criterion tests per requirement; semantic evaluation gate planned with the fixed eval set (DEBT-003, course gate 4) |

## VC-3 — Test layout

- `test/offline/` — deterministic, network-free, order-independent (QR-005);
  this is the suite CI blocks on.
- `test/live/` — needs API access, marked `integration`, excluded from the
  default selection (`pyproject.toml`); never a merge blocker.

## VC-4 — Course blocking gates → current status (honest map)

| # | Gate (project.pdf p10) | Status |
|---|---|---|
| 1 | Test approval gate | **live**: `test-approval-gate` job + `test-approved` label + PR template |
| 2 | Static analysis gates | **partial**: lint live; dependency audit advisory (DEBT-002); type-checking absent (DEBT-001); safe-path contract/security/API-surface/permission checks pending the S1 path list (DEBT-004) |
| 3 | Schema gate | **live**: `schema-gate` job over `docs/req/requirements.yaml` + template |
| 4 | Semantic evaluation gate | **planned**: needs `prompts/` versions + fixed eval set (DEBT-003) |
| 5 | Regression gate | **live**: full test matrix as required contexts on `main`; CI also runs on `integration` pushes |
| 6 | AI-use log gate | **live**: `ai-use-log-gate` job; hard effect begins when `docs/ai-use-log.yaml` is created at the team's formal kickoff (warning until then) |

Branch protection on `main` already requires CI success + one human review +
resolved conversations; safe-path CODEOWNERS lands with DEBT-004. Per the
branch model (AGENTS.md §9), `main` is PR-only (batch merges from
`integration` + important direct fixes, each pulled back into `integration`
immediately), so the PR-triggered gates fire at every batch merge into `main`;
`integration` itself takes routine direct pushes and is covered by
push-triggered CI (schema, lint, tests, advisory audit).

## VC-5 — QA records this rule set feeds

- `docs/review-memo.md` — one memo per PR, verdict APPROVE / CHANGES REQUIRED
  / REJECT.
- `docs/debt-register.md` — AI-era debt categories, each with a review trigger.
- `docs/bug-diary.md` — one entry per significant bug, including which
  invariant gap it exposed.
