# Project rules — always-on behaviour for coding agents

This file applies to every agent session in this repository. It is human-owned:
agents must never edit it. `AGENTS.md` (repository root) defines the reading
order and the editable/frozen zones; this file defines how an agent behaves
while working. If a task brief conflicts with these rules, the stricter rule
wins — stop and ask.

## 1. Start of work

- Read `AGENTS.md`, `Prompt.md`, and the relevant entries of
  `docs/req/requirements.yaml` before any action.
- Produce a plan (traceability, interface contracts, scope boundaries, test
  strategy, ordered steps) and STOP. Write no code until a human approves it.
- One stage at a time; stop at every stage gate.

## 2. Write scope

- Writes are limited to `src/**` and `test/**` unless the approved plan says
  otherwise.
- `docs/**`, `CHANGELOG.md`, `.github/**` and `.opencode/**` are human-owned.
  The single exception: you append your own entry to `docs/ai-use-log.yaml`.
- Never edit `.opencode/rules.md` or `.agent/rules.md`.
- Git is human work: never commit, push, branch, merge or rebase.

## 3. Requirement discipline

- Do not change the status, priority or statement of a registry entry unless
  the human explicitly instructs it.
- `TBD` stays `TBD`: never invent a threshold, percentage or numeric target.
  Propose the measurement instead.
- Cite the requirement/invariant ID that a test or code comment implements.

## 4. Safety

- Never read, write or echo `.env`, key files or any credential; redact
  key-shaped strings in output.
- Never alter rating semantics (`agents/rating.py`, `final_rating`).
- Changes to safety-critical paths (see `.opencode/permissions.jsonc`) require
  an ADR reference and human approval.

## 5. Evidence duty

- Every session that changes code, tests or prompts appends ONE entry to
  `docs/ai-use-log.yaml`, using the current schema:
  `id: AI-YYYY-MM-DD-<slug>`, `date`, `task`, `agent`, `model`, `prompt_ref`,
  `files`, `human_decision`, `verification`, `transcript`.
- Never rewrite or reorder existing entries; never invent an approval, a
  transcript path or a model name. If the human has not decided yet, write
  `human_decision: "pending"`.
- Report every intervention point (where the human redirected, approved or
  rejected work) in the session report.

## 6. Honesty

- If the code disagrees with the brief or the plan, stop and report the
  discrepancy; never improvise around an approved plan.
- If a request is ambiguous, ask. A wrong assumption is worse than a question.

## 7. Quality gate before reporting

- `ruff check .` passes; the full offline suite passes with zero regressions.
- New tests are offline, network-free, order-independent and cite their
  requirement ID; at least one negative test per feature.
- No new runtime dependencies.
- Report what was changed, the test evidence, and anything you could not verify.

