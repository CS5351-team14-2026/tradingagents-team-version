# Debt register — AI-era technical debt (deliverable D4, project.pdf p6)

Categories follow the course list: prompt rot, hallucinated dependencies,
untouchable code, hidden dependencies, agent-induced bloat, evaluation debt,
guardrail debt, human/cognitive debt. One row per debt; each carries a concrete
review trigger. Owner column is filled when someone claims it.

| ID | Category | Description | Risk if ignored | Review trigger | Owner |
|---|---|---|---|---|---|
| DEBT-001 | guardrail | Type-checking gate absent; baseline code is untyped and a repo-wide strict pass is unrealistic in the project window | type errors surface as runtime bugs in generated code | first new module lands → scope a type-check job to new modules only, grow the allowlist | 【认领】 |
| DEBT-002 | guardrail | Dependency audit (`pip-audit`) runs advisory (`continue-on-error: true`) until the first report is triaged; also the secret-scan CI job (SEC-001/INV-006 enforcement) is not yet added — tooling choice pending | known CVEs or leaked keys pass CI | team triages the first audit run → flip to blocking + add required context; choose secret-scan tool | 【认领】 |
| DEBT-003 | evaluation | Semantic evaluation gate (course gate 4) unbuilt: no `prompts/` versioning, no fixed eval set, no quality thresholds | prompt/model changes ship unmeasured | first `prompts/prompt_vX.Y.yaml` lands → build eval set + job | 【认领】 |
| DEBT-004 | guardrail | Safety-critical path list, CODEOWNERS, and safe-path static checks (contract/security/API-surface/permission) pending the S1 abuse-case round; initial assumed list lives in `.opencode/permissions.jsonc` `safety-critical-paths` guard | unsafe edits to rating/date/secret paths merge without ADR + dedicated review | S1 abuse-case round produces the path list → add CODEOWNERS + checks | 【认领】 |
| DEBT-006 | guardrail | Permission fitness function absent: CI does not yet assert that changed files fall inside the acting role's whitelist | role-whitelist drift goes unnoticed | architecture blueprint (S2) lands → implement structural fitness job | 【认领】 |
| DEBT-007 | human/cognitive | `.opencode/rules.md` and `.agent/rules.md` are empty awaiting human authorship (course human-only rule); `AGENTS.md` §7 temporarily carries the operative equivalents | covenant of record missing; agents governed only by agent-drafted files | next team meeting → humans author both files | 【认领】 |
| DEBT-008 | hidden dependency | AI-use log not yet created (team not formally kicked off): gate 6 runs in warning mode, so code-touching PRs are not yet log-enforced | supervision evidence gap if code work starts before kickoff | formal kickoff creates `docs/ai-use-log.yaml` → gate hardens automatically | 【认领】 |
