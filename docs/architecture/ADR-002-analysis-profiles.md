# ADR-002 — Three analysis profiles (quick / standard / deep)

- Status: Accepted (2026-11-13)
- Requirements: REQ-TA-FR-001 (must, implement); relates REQ-TA-INV-003, REQ-TA-QR-004, REQ-TA-GOV-003
- Supersedes: none. Extends the v0.7.1 baseline (AGENTS.md §3, SC-2).

## Context

The baseline exposes the four run-shaping settings separately and has no single
control tying them together:

- analyst set — graph default four analysts (`trading_graph.py` constructor),
  chosen interactively in the CLI (`cli/prompts.py:select_analysts`);
- debate budget `max_debate_rounds` (default 1, `default_config.py`);
- risk budget `max_risk_discuss_rounds` (default 1, `default_config.py`);
- per-analyst tool-round cap `max_tool_rounds` (default 20, `default_config.py`).

REQ-TA-FR-001 requires a named profile that sets these four together, rejects an
unknown profile before any model call, reproduces the baseline when no profile is
given, lets explicit settings override the profile per field, and records both the
requested and the resolved settings.

A profile budget of 0 does **not** mean "no debate": the graph runs the first
speaker before it consults the router
(`graph/setup.py` edges START→Bull Researcher and Trader→Aggressive Analyst;
`graph/conditional_logic.py`). A 0 budget would still ask the first Bull /
Aggressive analyst once, then branch. The approved profiles therefore use
budgets of at least 1 and never 0.

## Decision

### Approved mapping

| Profile  | Analysts | max_debate_rounds | max_risk_discuss_rounds | max_tool_rounds |
|----------|----------|------------------:|------------------------:|----------------:|
| quick    | market, news | 1 | 1 | 3 |
| standard | market, social, news, fundamentals | 1 | 1 | 20 |
| deep     | market, social, news, fundamentals | 3 | 3 | 20 |

### Resolution location and interface

A pure function `resolve_profile(profile, *, explicit, defaults, base_analysts)`
in `src/tradingagents/default_config.py` computes a `ResolvedProfile`
(`requested_profile`, the four settings, `overrides`). `TradingAgentsGraph`
calls it in its constructor **before** any model client is created, so an
unknown profile fails fast with an error naming the legal values
(`quick, standard, deep`).

- CLI: `--profile` (wins over `TRADINGAGENTS_PROFILE`) is validated at the very
  start of `run_analysis`, before the unattended-gap check, the interactive
  questions and graph construction.
- Python: `TradingAgentsGraph(selected_analysts=..., profile=..., explicit_overrides={...})`,
  where a `selected_analysts` list is an explicit analyst-set override.

### Input precedence (per field)

explicit input > profile mapping > baseline default.

Explicit inputs, by source:

- `--analysts` (recorded as `{"analysts": [...]}` even if identical to the
  profile's own set);
- `TRADINGAGENTS_MAX_DEBATE_ROUNDS`, `TRADINGAGENTS_MAX_RISK_ROUNDS`,
  `TRADINGAGENTS_MAX_TOOL_ROUNDS` — a *set* variable is an explicit source for
  its field, read at its written (coerced) value;
- Python `selected_analysts` — a caller-passed analyst list is an explicit
  analyst-set override, recorded in `profile_overrides`;
- Python `explicit_overrides` (e.g. `{"max_debate_rounds": 1}`), including
  `explicit_overrides["analysts"]`.

Two distinct analyst-set channels exist and must not be confused:

- **Python `selected_analysts`** is an *explicit override*: the caller named the
  set, so it is recorded in `profile_overrides`.
- **CLI `base_analysts`** (the graph's `base_analysts` argument, used only by the
  CLI entry point) *carries the menu's choice, or the profile mapping filtered
  for the asset type* (crypto drops `fundamentals`). It shapes the resolved
  analysts but is **not** recorded as an override.

When both explicit analyst inputs are supplied — a Python `selected_analysts` and
an `explicit_overrides["analysts"]` — `explicit_overrides["analysts"]` wins and is
the value recorded in `profile_overrides`. Only user-named inputs are recorded.

Example: `deep` with `TRADINGAGENTS_MAX_DEBATE_ROUNDS=1` resolves to debate 1,
risk 3, tool cap 20; the report shows `profile_overrides = {"max_debate_rounds": 1}`.

### No profile

`profile=None` (and no `TRADINGAGENTS_PROFILE`) applies no mapping: the four
settings come from the caller's config and the menu's analyst selection, the
environment is not re-read per field (so a legacy caller's config stays
authoritative), and the checkpoint signature is byte-for-byte the v0.7.1 one.

### Report metadata

`run_settings()` records, in its allowlist:

```
profile_requested:  "quick" | "standard" | "deep" | null
profile_overrides:  { "<field>": <value>, ... }   # only user-named inputs
profile_resolved:   { analysts, max_debate_rounds, max_risk_discuss_rounds, max_tool_rounds }
max_tool_rounds:    <int>
```

These reach the Markdown report header (`reporting.py`), the HTML report
(`report_html.py`) and the state log (`trading_graph._log_state`). The terminal
prints one "Effective configuration" line from the same `run_settings()`; the
selection step no longer prints the profile's raw debate/risk numbers, so a
stale "3 / 3" can never be mistaken for the effective settings.

### Checkpoint signature

`_run_signature` uses the resolved analysts and round caps; it appends a `tools=`
segment only when the effective tool cap differs from the caller's config value.
A legacy/omitted-profile call therefore keeps the pre-change signature for any
tool cap (20 or a custom one), while a profile or explicit override that changes
the analysts or rounds yields a distinct signature and never resumes a stale
checkpoint.

`claim_enforcement` (ADR-001; now defaults to True and settles claim acceptance
after the graph run) is excluded from the checkpoint signature: it does not
change the graph shape or the state written before acceptance, so a run that
predates the key and a run carrying the default share one signature and existing
checkpoints still resume.

## Consequences

- New code lives in `default_config.py` (mapping + resolver),
  `graph/trading_graph.py` (constructor wiring, `run_settings`, signature) and
  `cli/{main,run,selections}.py` (flag, validation order, questions, display).
- `run_settings()` grows the three profile fields and `max_tool_rounds`; the
  report header/HTML/state log render them. This aligns with, and does not
  conflict with, REQ-TA-QR-004 and REQ-TA-GOV-003 (their allowlist gains the
  tool cap and the profile block).
- The CLI adds `--profile`; when a profile is selected the analyst and research
  depth questions are skipped, and a headless run needs no `--analysts` or round
  env (other required inputs are still enforced).
- No new runtime dependency (SC-5).

## Re-evaluation triggers

- A profile wants a tool cap above 48 (requires raising `max_recur_limit`).
- Any profile wants a 0 budget (changes skip semantics; see Context).
- The architecture blueprint assigns the resolver to a different module
  (`docs/architecture/` is still absent; SC-1 mapping is provisional).
- FR-008 / GOV-003 finalise the `run_settings` allowlist differently.
