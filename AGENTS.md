# AGENTS.md — coding-agent entry point (deliverable D3)

This is the single entry point every AI coding agent reads before doing any
work in this repository. Human team members: review changes to this file like
changes to a contract — it constrains what agents may do (project.pdf p5 D3).

## 1. Build target

Enhance the TradingAgents stock-analysis agent (upstream v0.7.1 baseline) with
a set of agreed functional and non-functional requirements under the CS5351
agentic-SE rules: requirements are machine-readable, architecture artifacts
constrain the agent, all code is generated under human supervision, and every
claim is traceable. The authoritative requirement set is
`docs/req/requirements.yaml`.

## 2. Reading order (mandatory, before any plan or code)

1. `AGENTS.md` (this file)
2. `Prompt.md` — the launch workflow: plan first, human approval, staged build
3. `docs/req/requirements.yaml` — authoritative registry (schema-gated)
4. `docs/req/requirement-candidates.md` — non-authoritative brainstorm pool
   (background only; never treat it as committed scope)
5. `docs/architecture/` — blueprint, ADRs, invariants, trace matrix
   (artifacts land in S2; until then this directory may be partial — do not
   invent missing architecture, ask the human)
6. `docs/code-governance/` — structural constraints, verification constraints,
   tool manifest
7. `.agent/rules.md`, `.opencode/rules.md`, `.opencode/permissions.jsonc`

## 3. Code baseline

Upstream release v0.7.1 (merged as PR #1) plus the src-layout reorganisation
(PR #2). New work **extends** this baseline; it never replaces baseline
behaviour silently. Removing or changing existing baseline behaviour requires
an ADR and human approval (see `.agent/rules.md` once authored).

## 4. Editable / review-required / frozen zones

| Zone | Status for agents |
|---|---|
| `src/**`, `test/**` | editable, subject to §7 verification requirements and the test-approval gate |
| `prompts/**` | editable; any change triggers the semantic evaluation gate once it exists (DEBT-003) |
| `docs/**`, `tools/ci/**`, `.github/**` | editable for governance work, but workflow changes require human review in the PR |
| `.opencode/rules.md` | **human-only** — agents must never write it (project.pdf p6) |
| `.env`, any secret-bearing file | **never read, never write, never echo** |
| `CHANGELOG.md` released sections, `LICENSE`, upstream release workflows | frozen (append-only for CHANGELOG's Unreleased section) |

## 5. Module organisation

```
src/tradingagents/   agents/ (analysts, researchers, managers, trader, risk_mgmt;
                     structured.py, rating.py, schemas.py, state.py, context.py)
                     graph/ (setup, trading_graph, conditional_logic, propagation,
                     analyst_execution, checkpointer)
                     dataflows/ (vendors, date_window, errors, net, symbols, ...)
                     memory/  llm_clients/  default_config.py  reporting.py
                     report_html.py  backtest.py  portfolio.py
src/cli/             main, run, stats_handler, display, prefs, models, ...
```

One architectural element maps to exactly one module
(`docs/code-governance/structural-constraints.md`); the element→module mapping
table is finalised with the architecture blueprint (S2).

## 6. Integration contracts between modules

To be fixed when the first cross-requirement slices start (planned: token
accounting exposed from `cli/stats_handler.py` to graph callers; the
profile→settings mapping; the shared evidence-citation format for FR-03/FR-05).
Until an interface is written here, agents must not invent cross-module APIs —
propose them in the execution plan and wait for approval.

## 7. Verification requirements for generated code

- `ruff check .` passes (strict, full repo)
- the full offline suite passes (`pytest -q`, network-free, zero regressions
  against the previous round)
- every touched requirement with status `implement` has a test matching its
  `fit_criterion`; every invariant has a negative test that fails on violation
- tests cite the requirement/invariant ID they verify
- live/API-dependent tests go under `test/live/` and are marked `integration`
- registry changes must pass the schema gate (`docs/req/req-schema.json`)
- every agent session behind a PR is recorded in `docs/ai-use-log.yaml`
  (gate 6), once that file exists at the team's formal kickoff

## 8. Working rules

- Start from `Prompt.md`; never run unattended end-to-end; stop at every human
  gate.
- Don't invent thresholds: where the registry says `TBD`, say `TBD` and run the
  baseline experiment instead of guessing a number.
- Record interventions: when a human redirects/approves/rejects your work,
  that belongs in the session transcript and the AI-use log entry.

## 9. Branch model (SCM)

| Branch | Role | How changes land |
|---|---|---|
| `main` | protected mainline | **PRs only** — CI must pass + human review (branch protection). Two kinds of PRs land here: periodic batch merges from `integration`, and important updates merged directly. |
| `integration` | working integration branch | exists to **reduce manual PR count**: routine work is pushed directly (or via PR when the author wants review). Periodically batch-merged back to `main` via PR; immediately after `main` changes, `main` is pulled back into `integration`. |
| `feat/**`, `gates/**`, `docs/**` | optional feature branches | for risky or reviewable work; merged into `integration` (PR or direct), following the `integration` rules above. |

Consequences for agents:

- After any `main` change (batch or direct), run/fetch `git pull origin
  integration` state — `integration` is rebased on `main` right away; never
  let the two diverge for long.
- PR-triggered course gates (test approval, AI-use log) fire on **every PR**,
  so they bite at each batch merge into `main` and on any review-wanted PR
  into `integration`. Push-triggered CI on `integration` continuously covers
  schema, lint, tests, and the advisory audit.
- The submission zip is cut from `main` (after the final batch merge).
