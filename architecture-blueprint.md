# Architecture blueprint — CS5351 team-app

> Master constraining document (deliverable D2.1). Plan agents and coding agents
> read this before any change; `AGENTS.md` defines the reading order and the
> editable/frozen zones. Requirement IDs refer to `docs/req/requirements.yaml`.

## 1. Scope

The application enhances TradingAgents v0.7.1 (an LLM-driven stock-analysis
pipeline) with a governed, measured, and auditable agentic workflow. The
delivered requirement set is 14 `implemented` entries plus 4 `restate`
invariants; 10 entries are explicitly `candidate`/`wont` and are out of scope
by team decision (`docs/architecture/option-ledger.md` records why).

In scope: analysis profiles, per-run token budget with controlled termination,
final-decision validation, material-claim traceability with fail-closed
acceptance, baseline-vs-enhanced comparison with recorded live evidence,
settings replay, run metadata, offline testability, secret redaction with a
PR-blocking scan, and the governance artefacts that keep all of the above
verifiable.

Out of scope (deliberately dropped, with reasons in the option ledger):
structured Bull/Bear debate (FR-003), the run-status enum (FR-006), token-cost
target (COST-001), the governance requirement family GOV-001..005, and the
invariants INV-004/INV-006 as new builds.

## 2. Architectural drivers

| Driver | Source | Architectural response |
| --- | --- | --- |
| Runs are slow and token-burning | REQ-TA-PERF-001, COST-001 (wont) | Analysis profiles (ADR-002) and a per-run budget over *optional* calls (ADR-004) |
| AI output must be constrained by deterministic code | REQ-TA-INV-005, FR-004, FR-005 | Deterministic claim audit + fail-closed acceptance (ADR-001); deterministic rating validation (ADR-003) |
| Traceability end-to-end | REQ-TA-QR-002, QR-004, GOV-003 (wont) | Claim→report-artifact links, run metadata, trace matrix, AI-use log |
| Zero silent failure | REQ-TA-QR-001 | Controlled failure codes and a machine-readable failure record (ADR-005) |
| Secrets must never leak | REQ-TA-SEC-001 | Redaction at output boundaries + PR-blocking secret scan with a reviewed baseline (ADR-006) |
| Measurements must be honest | REQ-TA-FR-007, PERF-001 | Paired evaluation protocol with frozen sources and committed evidence (ADR-007) |
| All code is agent-generated and supervised | Course rule | Governance files, permission model, transcripts, AI-use log, CI gates |

## 3. System boundary

```
CLI (src/cli) ──► TradingAgentsGraph (src/tradingagents/graph)
                     ├─ analysts (parallel subgraphs, tool rounds capped)
                     ├─ bull/bear debate ──► research manager
                     ├─ trader ──► risk debate ──► portfolio manager
                     ├─ memory log (settle + reflect)
                     └─ run record: budget ledger, claim audit, failure block
   ▲                    │
   │                    ├─► dataflows (vendors, point-in-time clamps, errors)
   │                    ├─► llm_clients (provider clients, usage normalization)
   │                    └─► reporting (markdown + html; claim ledger; acceptance)
   └── evaluation runner (src/tradingagents/evaluation*.py) ──► docs/evidence/*
```

External systems: LLM providers and market-data vendors. Both are reached only
through `llm_clients/**` and `dataflows/**`; tests replace them with doubles
(REQ-TA-QR-005).

## 4. Components and module mapping

Each architectural element maps to exactly one module (see
`docs/code-governance/structural-constraints.md` SC-1):

| Element | Module |
| --- | --- |
| Agent roles (analysts, researchers, managers, trader, risk) | `src/tradingagents/agents/**` |
| Orchestration, stop conditions, run record | `src/tradingagents/graph/**` |
| Data access, point-in-time rules, failure taxonomy | `src/tradingagents/dataflows/**` |
| Provider abstraction and usage normalization | `src/tradingagents/llm_clients/**` |
| Memory, settlement, reflection | `src/tradingagents/memory/**` |
| Per-run budget and usage ledger | `src/tradingagents/run_budget.py` |
| Run metadata and failure record | `src/tradingagents/run_record.py`, `src/tradingagents/failure.py` |
| Report rendering, claim ledger, acceptance | `src/tradingagents/reporting.py`, `report_html.py` |
| Paired evaluation | `src/tradingagents/evaluation*.py` |
| Configuration and profiles | `src/tradingagents/default_config.py` |
| Interactive UX and commands | `src/cli/**` |

## 5. Authority boundaries

| Artefact | Authority |
| --- | --- |
| `docs/req/requirements.yaml`, ADRs, `docs/architecture/invariants.md`, `.opencode/permissions.jsonc`, `AGENTS.md` | **authoritative** — code and agents must conform |
| `docs/req/requirement-candidates.md`, `risk-list.md`, `option-ledger.md`, session notes | **advisory** — background, never committed scope |
| Anything an agent says without a cited artefact | **non-authoritative** |

Deterministic code outranks the model: the claim audit, rating validation,
budget stop, point-in-time clamps and redaction run in Python and cannot be
overridden by prompt text.

## 6. Agent workflow

The graph executes: `START → analysts ∥ memory-settle → bull⇄bear debate →
research manager → trader → risk debate → portfolio manager → END`, with
`max_debate_rounds`, `max_risk_discuss_rounds`, `max_tool_rounds` and the
recursion limit bounding every loop. Analysis profiles (ADR-002) resolve the
analyst set and the three round budgets *before* any client is created; an
invalid profile fails before any LLM call. Optional LLM calls consult the
budget ledger first (ADR-004): once recorded usage reaches the limit, no new
optional call starts, while required synthesis is still attempted and may end
in a controlled `REVIEW` failure record (ADR-005).

Coding-agent workflow (the workflow *we* run) is defined by `Prompt.md`:
plan → human approval → staged build → self-verification, with human gates at
every stage.

## 7. Permissions

Default deny: an agent may read and write nothing unless a path is on its
role's whitelist (`docs/architecture/permission-model.md`,
`.opencode/permissions.jsonc`). Human-only: `.opencode/rules.md`, PR approval,
`test-approved` and `secret-baseline-approved` labels, branch-protection
changes.

## 8. Verification strategy

Three layers (`docs/code-governance/verification-constraints.md`):

1. **Structural** — imports, module boundaries, lint, schema validation of the
   registry, permission fitness.
2. **Regression** — the full offline suite on every change, py3.11–3.14 plus a
   non-UTC run, zero regressions.
3. **Behavioural** — fit-criterion tests per requirement, negative tests per
   invariant, the paired evaluation evidence for performance claims.

Six blocking gates in CI (project.pdf p10): test approval, static analysis,
requirements schema, semantic evaluation (recorded as debt DEBT-003 with
grounded trigger paths), regression, AI-use log; plus the SEC-001 secret scan
with a reviewer-approved baseline.

## 9. Observability

Every run records: the allowlisted `run_settings` block (provider/model per
tier, analysts, rounds, vendors, profile requested/overrides/resolved),
`run_metadata` (status, failure code/phase/diagnostic), the budget ledger
(status, reason codes, known tokens, usage state, blocked calls), the claim
audit (ACCEPTED/DOWNGRADED/NOT_ASSESSED with per-claim resolution) and the
claim acceptance verdict (ACCEPTED/REJECTED/NOT_ENFORCED). The state log, the
report header and the memory log are the three durable surfaces.

## 10. Change policy

- Requirement changes go through the registry (status lifecycle + schema gate);
  prompt changes are requirement changes (GOV-001, wont — still the operating
  rule) and must be recorded in the AI-use log.
- Changes to safety-critical paths (`.opencode/permissions.jsonc`
  `safety-critical-paths`) require a referenced ADR and human approval.
- ADRs are append-only: superseding decisions add a new ADR or an amendment
  section (ADR-004 has one; ADR-001 §4 records the fail-closed activation).
- New runtime dependencies require an ADR.

## 11. Reading order for the Plan agent

`AGENTS.md` → `Prompt.md` → `docs/req/requirements.yaml` →
`docs/architecture/adr/**` → this blueprint →
`docs/code-governance/**` → `.agent/rules.md` → `.opencode/rules.md`.
