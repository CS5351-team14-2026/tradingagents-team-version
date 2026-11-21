# Permission model

> Deliverable D2.6. Default is **no read and no write**; every granted path is
> an explicit whitelist entry. Machine-readable source of truth:
> `.opencode/permissions.jsonc`. This document is the human-readable mirror and
> records how the model was enforced in practice.

## 1. Roles and file-level grants

| Role | Read | Write |
| --- | --- | --- |
| `planner` | `AGENTS.md`, `Prompt.md`, `README.md`, `docs/**`, `src/**`, `test/**`, `pyproject.toml` | **nothing** (plan only) |
| `coder` | `AGENTS.md`, `Prompt.md`, `docs/**`, `src/**`, `test/**`, `prompts/**`, `pyproject.toml` | `src/**`, `test/**`, `prompts/**` |
| `verifier` | same as coder | `test/**` |
| `reviewer` | `**` | `docs/review-memo.md`, `docs/debt-register.md`, `docs/bug-diary.md` |

Anything not listed is denied. In particular no role may write
`.opencode/rules.md` (human-only), workflows, or the requirements registry
without the schema gate and human review.

## 2. Guards (cross-role)

| Guard | Rule | Enforcement |
| --- | --- | --- |
| `no-secrets` | Never read, write or echo `.env`, key files, or `*(.env|*.key|*secret*)` | Session config + CI secret scan (SEC-001, ADR-006) |
| `human-only-rules-files` | `.opencode/rules.md` is human-only; `.agent/rules.md` is authored by humans; agents propose via PR description | Human review |
| `workflow-changes-need-human-approval` | Writes under `.github/**` are governance decisions requiring explicit human approval | Branch protection + review |
| `registry-schema-gated` | `docs/req/requirements.yaml` must pass `docs/req/req-schema.json` | CI schema gate (course gate 3) |
| `safety-critical-paths` | Changes require a referenced ADR and human approval: `agents/rating.py`, `dataflows/date_window.py`, `dataflows/errors.py`, `dataflows/net.py`, `dataflows/symbols.py`, `llm_clients/api_key_env.py` | Human review; CODEOWNERS pending (DEBT-004) |

## 3. Human-only actions

- Approving PRs and merging into `main` (branch protection: one human
  approval, last-push approval required, stale approvals dismissed).
- Adding the `test-approved` label (course gate 1) and the
  `secret-baseline-approved` label (SEC-001 baseline changes).
- Changing branch protection or gate design.
- Authoring `.opencode/rules.md` and `.agent/rules.md`.

## 4. Defence in depth

1. **Session level** — the OpenCode session loads the role whitelist; in
   practice each member fed a task-specific `AGENTS.md`/prompt to their own
   session and the whitelist was restated per task (Base constraints).
2. **Repository level** — CI gates and branch protection catch what a session
   misses: schema gate, AI-use log gate, test-approval gate (PR references a
   `test-approved` issue), secret scan (baseline changes need a reviewer
   label), full regression matrix, advisory dependency audit.
3. **Human level** — every PR is reviewed; `docs/review-memo.md` records the
   verdict (APPROVE / CHANGES REQUIRED / REJECT).

## 5. Known gaps

- The permission fitness function (CI asserting that a diff stays inside the
  acting role's whitelist) is recorded as DEBT-006; enforcement today is by
  session configuration and review.
- CODEOWNERS on safety-critical paths is pending reviewer handles (DEBT-004);
  the path list itself is fixed and versioned in the guards above.
