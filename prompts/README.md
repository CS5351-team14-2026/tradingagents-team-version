# prompts/ — versioned runtime prompt snapshots

The application's LLM prompts live **inline in code** (agent factories under
`src/tradingagents/agents/**`, schema field descriptions in
`agents/schemas.py`, the reflection prompt in `memory/reflection.py`, and the
withhold notices in `dataflows/date_window.py`). The files here are versioned
snapshots of the decision-critical prompt surfaces, extracted verbatim from the
code at a recorded git ref.

## Governance rule

- A prompt change is a requirement change: edit the code, update the snapshot,
  and record the session in `docs/ai-use-log.yaml` (REQ-TA-GOV-001 as an
  operating rule; the semantic-evaluation gate is DEBT-003).
- Snapshots are **extracted from code**, never hand-written from memory. Each
  file records its `source.ref` and `source.file`.
- `v1.0` is the upstream baseline; `v1.1` is the current integration tree. The
  `changes_from_v1_0` list is the reviewable diff.

## Files

| File | Version | Source | Surface |
| --- | --- | --- | --- |
| `prompt_v1.0.yaml` | 1.0 | `origin/baseline/v0.7.1` | Portfolio Manager decision prompt (baseline, free text) |
| `prompt_v1.1.yaml` | 1.1 | `integration` | Portfolio Manager decision prompt (material claims, confidence, primary analyst evidence) |

## Scope

These snapshots cover the final-decision surface because it is the one the
claim audit, rating validation and report rendering all depend on. The
analyst/trader/research prompts are not snapshotted; their changes are still
covered by the AI-use log rule and by the offline prompt tests
(`test/offline/test_structured_agent_prompts.py`).
