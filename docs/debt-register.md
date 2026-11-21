# Debt register — AI-era technical debt (deliverable D4, project.pdf p6)

Categories follow the course list: prompt rot, hallucinated dependencies,
untouchable code, hidden dependencies, agent-induced bloat, evaluation debt,
guardrail debt, human/cognitive debt. One row per debt; each carries a concrete
review trigger. Rewritten 2026-11-21 from the actual repository state.

| ID | Category | Description | Risk if ignored | Review trigger | Owner |
|---|---|---|---|---|---|
| DEBT-001 | guardrail | Type-checking gate absent; the baseline code is untyped and a repo-wide strict pass is unrealistic in the project window | Type errors surface as runtime bugs in generated code | First new module lands → scope a type-check job to new modules only, grow the allowlist | team |
| DEBT-002 | guardrail | Dependency audit (`pip-audit`) runs advisory (`continue-on-error: true`); findings do not block. The secret-scan gate is now live and is not part of this debt | Known CVEs pass CI | Dependency set freezes at packaging → triage the audit report and flip to blocking | team |
| DEBT-003 | evaluation | Semantic evaluation gate (course gate 4) unbuilt: no fixed eval set and no replay job. Versioned prompt snapshots now exist under `prompts/`; the trigger paths are `src/tradingagents/agents/**`, `agents/schemas.py`, `memory/reflection.py`, `dataflows/date_window.py`, `prompts/**` | Prompt/model changes ship unmeasured | A prompt or model change after the snapshots are adopted | team |
| DEBT-004 | guardrail | Safety-critical path list is grounded and recorded in `.opencode/permissions.jsonc` (`safety-critical-paths`): `agents/rating.py`, `dataflows/{date_window,errors,net,symbols}.py`, `llm_clients/api_key_env.py`. Safety-path changes are reviewed through main branch protection (1 approval) and the `safety/` PR route with an ADR; no CODEOWNERS file is used (not a course deliverable). Still missing: safe-path CI checks (contract/security/API-surface/permission) — they wait for the S2 ADRs so they do not block necessary edits to these files | Unsafe edits to rating/date/secret paths merge without a dedicated check | S2 ADR-001 lands → add safe-path checks | team |
| DEBT-005 | evaluation / cost | No context compaction or constraint re-injection. Prompt size is bounded only by structural caps (news 20/10, memory 5+3, claims 3+3, tool rounds, debate rounds); conversation history is never summarised. Standing constraints are re-sent verbatim on every call, but there is no post-compaction re-injection because compaction does not exist (see `docs/architecture/context-design.md`) | A high-cap configuration can produce very large prompts; prompt cost grows with rounds | A run is configured with high round caps, or a provider enforces a hard context window the caps cannot respect | team |
| DEBT-006 | guardrail | Permission fitness function absent: CI does not assert that changed files fall inside the acting role's whitelist | Role-whitelist drift goes unnoticed | Architecture blueprint (S2) lands → implement the structural fitness job | team |

## Closed since the foundation slice (for the record)

- **AI-use log gate**: `docs/ai-use-log.yaml` exists and is enforced by the
  `ai-use-log-gate` job.
- **Secret scan**: `secret-scan` (pinned detect-secrets 1.5.0, base-baseline
  comparison, `secret-baseline-approved` label) is live.
- **Safety-path list**: grounded from the source analysis and recorded in the
  permission model.
