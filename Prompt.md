# Prompt.md — static launch prompt (deliverable D9)

You are the AI coding agent for this repository. `AGENTS.md` is your entry
point; after reading it and its reading order, follow exactly this workflow.
This prompt is a launch instruction only — it does not authorise an unattended
end-to-end run (project.pdf p7 D9).

## Step 1 — Understand

- Read the `AGENTS.md` reading order in full.
- Restate the task in your own words, citing the requirement IDs
  (`REQ-TA-...`) it touches. If the task maps to no registry entry, or to an
  entry whose status is `candidate`, stop and ask the human; do not invent
  requirements or thresholds.

## Step 2 — Plan (before any code)

Produce an execution plan containing:

1. **Traceability** — requirement/invariant IDs ↔ planned steps ↔ files
2. **Interface contracts** — signatures/behaviours of anything crossing module
   boundaries (see AGENTS.md §6; propose, don't assume)
3. **Scope boundaries** — files you will create/modify, and files you
   explicitly will not touch
4. **Testing strategy** — the offline test per fit criterion, the negative
   test per invariant, and how the full previous suite stays green
5. **Steps** — ordered, each small enough to verify independently

## Step 3 — STOP and wait

Present the plan and **stop**. Do not write, modify, or delete any code until
the human explicitly approves the plan. Log this approval point; it becomes an
annotated intervention in the session transcript.

## Step 4 — Build in stages (after approval)

- Implement one stage at a time, extending the baseline, never replacing it.
- After each stage: run `ruff check .` and the offline suite; report results
  before moving on. The human gates each stage transition.
- Stay inside the plan's scope boundaries. Needing to exceed them means
  stopping and re-planning (back to Step 2), not improvising.

## Step 5 — Self-verify

- Full offline suite: zero regressions.
- Fit-criterion tests and invariant negative tests for the touched
  requirements, each citing its ID.
- Summarise the evidence for the trace matrix (component, test, monitor).

## Hard rules

- Never read, write, or echo secrets (`.env`, API keys).
- Never touch frozen zones (AGENTS.md §4).
- Where the registry says `TBD`, output `TBD` and propose the baseline
  experiment — never invent a number.
- Every session that changes code or prompts gets an entry in
  `docs/ai-use-log.yaml` (once created at kickoff; gate 6 enforces it).
