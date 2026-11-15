# Structural constraints — module organisation rules (deliverable D3)

These rules bind how AI-generated code may be organised. They are checked in
human review (`docs/review-memo.md`) and, where marked, by CI.

## SC-1 — One architectural element, exactly one module

Every architectural element maps to exactly one module, and every module
realises exactly one element. The authoritative element→module mapping lands
with the architecture blueprint (S2). Until then the provisional reading is:

| Provisional element | Module |
|---|---|
| Agent role implementations (analysts, researchers, managers, trader, risk) | `src/tradingagents/agents/**` |
| Graph orchestration (execution order, stop conditions, rounds) | `src/tradingagents/graph/**` |
| Data access layer (vendors, date windowing, errors, symbols) | `src/tradingagents/dataflows/**` |
| LLM client abstraction | `src/tradingagents/llm_clients/**` |
| Analysis memory/state | `src/tradingagents/memory/**` |
| Cross-cutting defaults & settings | `src/tradingagents/default_config.py` |
| Report rendering | `src/tradingagents/reporting.py`, `report_html.py` |
| Deterministic comparison/evaluation runs | `src/tradingagents/backtest.py` |
| Interactive UX + command surface | `src/cli/**` |

## SC-2 — Extend the baseline, never replace it

New work extends the v0.7.1 baseline (AGENTS.md §3). Silently changing or
removing existing baseline behaviour is a review REJECT; it requires an ADR
plus human approval first (see the project covenant once
`.agent/rules.md` is authored).

## SC-3 — Every module and function cites what it realises

Each new/changed module (docstring) and function (comment) references the ADR
ID and the requirement/invariant IDs it implements, e.g.
`Implements: ADR-002; REQ-TA-FR-001; REQ-TA-INV-003`. This is what keeps the
trace matrix (D2.4) fillable from code.

## SC-4 — Authority boundaries

| Artifact class | Authority |
|---|---|
| `docs/req/requirements.yaml`, ADRs, `docs/architecture/invariants.md`, `.opencode/permissions.jsonc`, `AGENTS.md` | **authoritative** — code and agents must conform |
| `docs/req/requirement-candidates.md`, risk list, option ledger, session notes | **advisory** — background, never committed scope |
| Anything an agent says without a cited artifact | **non-authoritative** |

## SC-5 — Dependencies

New runtime dependencies (`pyproject.toml`) require an ADR and human approval
(hallucinated-dependency control). CI installs from declared metadata only;
the clean-install smoke job fails on undeclared runtime imports.

## Enforcement

- SC-1/SC-3/SC-4/SC-5: human review per PR (`docs/review-memo.md` checklist).
- SC-2: review + targeted tests.
- Import-layering fitness function over the module boundaries above is
  planned with the blueprint (DEBT-006 in `docs/debt-register.md`).
