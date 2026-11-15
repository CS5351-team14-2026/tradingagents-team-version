# Candidate Requirements Catalogue

> Non-authoritative brainstorming document. See §1 for status.

## Document metadata

- **Status:** Draft for team review. Not approved; not implementation-ready.
- **Baseline branch and commit:** `integration` at `b1d79dd`.
- **Review date:** 2026-11-12.
- **Authoring:** OpenCode-assisted generation, directed and reviewed by the
  human team.
- **Authoritative registry path:** Not yet confirmed. As of this baseline, the
  only requirements artefact on `integration` is the template
  `doc/req/req-registry-template.yaml` (note the singular `doc/`). The
  project specification depicts `docs/req/requirements.yaml` (plural `docs/`),
  but that file does not exist yet; the team must confirm the final path before
  it is treated as authoritative.

## 1. Purpose and status

This document is a **non-authoritative brainstorming catalogue** of candidate
functional requirements, non-functional requirements, and invariants for the
TradingAgents enhancement project. It exists so that all six group members can
compare ideas, spot overlaps, and choose their individual requirements.

- **Inclusion does not mean approval or commitment.** A candidate listed here is
  not an agreed requirement and imposes no obligation on the team.
- **Nothing here is implementation-ready.** Selected requirements must later be
  written into the authoritative YAML registry in the team's registry format and
  must pass schema validation before they count as real requirements.
- **The authoritative registry has not yet been created** as of this baseline.
  The project specification depicts `docs/req/requirements.yaml` (plural
  `docs/`), but that file does not exist yet, and the only artefact present on
  `integration` is the template `doc/req/req-registry-template.yaml` (singular
  `doc/`). Throughout this document, `docs/req/requirements.yaml` therefore
  refers to the **project-specification or planned path**, not an existing
  file. The team must confirm the final path.
- **IDs in this document are temporary candidate labels**, not reserved registry
  IDs. The labels used here (e.g. `CAND-FR-01`, `CAND-NFR-01`, `CAND-INV-01`)
  are placeholders for discussion only. A candidate that is later accepted will
  receive a proper `REQ-TA-<TYPE>-<NNN>` identifier in the authoritative
  registry.
- **The authoritative machine-readable registry is separate from this file.**
  This Markdown file must never be treated as the source of truth for
  requirements.

Nothing in this document reserves an official requirement ID, changes any
authoritative requirements YAML, or modifies source, tests, architecture,
workflows, or OpenCode permissions.

## 2. Selection guidance

When choosing a requirement to own, each member should weigh:

- **Meaningful improvement over the baseline.** Prefer work that changes
  behaviour in a way a reviewer can see, not a cosmetic refactor.
- **Alignment with the project specification.** The course rewards reduced
  token consumption, structured agent collaboration, deterministic safety
  boundaries, traceability, verification, GitHub blocking gates, ADD, and
  production-grade operation.
- **Implementation effort.** Keep the candidate small enough that one person can
  own it end to end within the semester.
- **Offline testability.** The candidate should have at least one deterministic,
  network-free test (the repository already separates `test/offline` from
  `test/live`).
- **Measurable fit criteria.** The requirement must be checkable by a machine,
  ideally by a test that fails when the behaviour regresses.
- **Architectural cohesion.** The candidate should map to a recognisable module
  rather than cut across many.
- **Dependencies on other candidates.** Note prerequisites and keep the critical
  path short.
- **Safety and security impact.** Zero-tolerance boundaries (invariants) are
  especially valuable evidence for the rubric.
- **Token and runtime impact.** Prefer changes that reduce cost, or at least do
  not inflate it.
- **Visibility in the final demonstration.** The candidate should produce
  something a live demo can show.
- **Overlap with another member's work.** Prefer distinct, non-overlapping
  primary requirements.

## 3. Functional-requirement candidates

Baseline status legend:

- **NEW** — the behaviour does not exist in the baseline and would be built.
- **PARTIAL** — some supporting pieces exist, but the requirement's observable
  behaviour does not.
- **EXISTING-UNVERIFIED** — the behaviour appears to exist but lacks a
  dedicated test that would fail if it regressed.
- **DUPLICATE** — the behaviour already exists and is already covered by tests.

### CAND-FR-01 — Configurable analysis profiles (quick / standard / deep)

- **Shall statement:** The system shall let the user select a named analysis
  profile (such as quick, standard, or deep) before analysing a stock, where the
  profile determines the analyst set, the debate-round budget, the risk-discussion
  budget, and the per-analyst tool-round cap.
- **Value:** Gives the user an explicit, named control over the cost/quality
  trade-off that the baseline only exposes through several unrelated settings.
- **Baseline status:** **PARTIAL**.
- **Repository evidence:**
  - `src/tradingagents/default_config.py` exposes the building blocks --
    `max_debate_rounds`, `max_risk_discuss_rounds`, `max_tool_rounds` -- and the
    `TRADINGAGENTS_*` env-override table `_ENV_OVERRIDES`.
  - `src/tradingagents/graph/setup.py` builds the analyst set from
    `selected_analysts` and enforces `max_tool_rounds` per analyst.
  - `max_risk_discuss_rounds` governs the risk-management discussion rounds and
    is a separate budget from `max_debate_rounds`; both are currently independent
    settings, with no profile tying them together.
  - There is **no** single `profile` key and no CLI/flag that selects one
    (verified: no `profile` option in `src/cli/main.py`).
- **Proposed fit criterion:** Given an **eventually approved profile-to-settings
  mapping** (the team must finalise it; see the illustrative table below), a
  valid profile value applies that mapping so that the analyst set,
  `max_debate_rounds`, `max_risk_discuss_rounds`, and `max_tool_rounds` all match
  the approved values for the chosen profile. An invalid profile value is
  rejected **before any LLM call** with an error that names the legal values. An
  unset profile reproduces the existing baseline defaults exactly. The report's
  run metadata records both the **requested** profile/settings and the
  **resolved** settings actually used. A precedence rule (below) decides what
  happens when a profile and explicit settings are both given.
- **Precedence rule:** When a profile and one or more explicit settings are both
  supplied, the explicit setting overrides the profile's value for that specific
  key only; all other keys take the profile's value. This precedence must be
  documented and tested so the resolved settings are deterministic. (Whether the
  team ultimately chooses "explicit wins per key" or "profile wins" is a design
  decision; the requirement fixates the chosen rule, not a particular choice.)
- **Illustrative mapping (NOT approved values):**
  The table below is an example to make the requirement concrete. These are
  **illustrative only** and must not be read as agreed values; the team approves
  the real mapping later.

  | Profile | Analyst set | max_debate_rounds | max_risk_discuss_rounds | max_tool_rounds |
  | --- | --- | --- | --- | --- |
  | quick (illustrative) | reduced subset (illustrative) | lower value (illustrative) | lower value (illustrative) | lower cap (illustrative) |
  | standard (illustrative) | default team (illustrative) | default value (illustrative) | default value (illustrative) | default cap (illustrative) |
  | deep (illustrative) | larger set (illustrative) | higher value (illustrative) | higher value (illustrative) | higher cap (illustrative) |

  Every cell above is a placeholder and **non-approved**. `max_tool_rounds` is
  deliberately part of the profile so a profile can bound per-analyst tool usage
  as well as rounds; `max_risk_discuss_rounds` should be considered part of the
  profile because the risk phase consumes LLM calls at the same order of cost as
  the debate phase.
- **Likely enforcing components:**
  `src/tradingagents/default_config.py`, `src/tradingagents/graph/setup.py`,
  `src/tradingagents/graph/trading_graph.py` (`run_settings`),
  `src/cli/main.py`.
- **Difficulty:** Low–Medium.
- **Dependencies / overlaps:** Depends on none for its core. Overlaps CAND-FR-02
  (budget) and CAND-NFR-01 (token efficiency) because profiles are the natural
  lever those measure; coordinate with their owners.
- **Risks / design decisions:** The approved mapping of profile to
  (analyst set, `max_debate_rounds`, `max_risk_discuss_rounds`, `max_tool_rounds`)
  is a design decision left to the team. Also decide how `selected_analysts`
  interacts with the profile and confirm the precedence rule above.
- **Suggested demo evidence:** Run the same ticker/date at two profiles and show
  the report metadata listing requested versus resolved settings and the
  differing agent/round counts.

### CAND-FR-02 — Per-run token and cost budget with deterministic fallback

- **Shall statement:** The system shall accept a maximum token budget for one
  analysis run and shall begin no further optional LLM calls once the recorded
  usage for the run reaches or exceeds that budget. Because providers generally
  report usage only after a call completes, the requirement bounds *subsequent*
  optional calls rather than promising an exact hard cap on the call in flight.
- **Value:** Directly addresses the course's "slow and token-burning" criticism
  and gives a demonstrable, deterministic cost ceiling on optional work.
- **Baseline status:** **NEW** (supporting signal exists, enforcement does not).
- **Repository evidence:**
  - Token accounting exists only in the CLI: `src/cli/stats_handler.py`
    (`StatsCallbackHandler` accumulates `tokens_in`/`tokens_out`) wired from
    `src/cli/run.py`. It is **not** available to
    `TradingAgentsGraph.propagate()` callers.
  - `src/tradingagents/default_config.py` has `max_tokens` (a per-call output
    cap) but **no** per-run budget and no budget-driven stopping logic.
  - No `--token-budget` flag exists in `src/cli/main.py`.
- **Proposed fit criterion:** With a configured token budget `N`, the run
  accumulates the usage reported by each LLM call. Once accumulated usage
  reaches or exceeds `N`, no **subsequent optional** LLM call is started (for
  example, no new optional debate or risk-discussion round). The run terminates
  with one of a defined set of controlled statuses (for example:
  `BUDGET_OK`, `BUDGET_WARNING`, `BUDGET_EXHAUSTED`), each with a
  machine-readable reason. The report states the recorded total when usage was
  available. A single in-flight call may push recorded usage past `N`; the
  requirement does not claim an exact hard cap.
- **Behaviour when usage is unavailable:** If a provider does not report usage,
  the run records usage as unavailable rather than estimating it silently, marks
  the affected status accordingly, and does not pretend the budget was enforced
  precisely. The team must decide whether available-but-partial usage still
  triggers the stop; this is a design decision, stated explicitly rather than
  assumed.
- **Report-generation caveat:** The requirement does **not** guarantee that final
  report generation always completes within the budget. It may reserve a portion
  of the budget for a final synthesis turn (the reserve percentage is **TBD**
  until measured), but if the budget is exhausted first, the run must end in a
  controlled status (for example `BUDGET_EXHAUSTED`) rather than an uncaught
  error, and the report must say that generation was curtailed.
- **Likely enforcing components:**
  `src/cli/stats_handler.py` (extend into a shared budget tracker),
  `src/tradingagents/graph/conditional_logic.py` and/or
  `src/tradingagents/graph/setup.py` (stop condition),
  `src/tradingagents/default_config.py`, `src/cli/main.py`.
- **Difficulty:** Medium.
- **Dependencies / overlaps:** Depends on exposing token accounting outside the
  CLI (shared with CAND-NFR-07 observability). Provides the mechanism that
  CAND-NFR-01 (token efficiency) and CAND-FR-07 (comparison mode) measure.
  Complements CAND-FR-01.
- **Risks / design decisions:** Token usage is provider-dependent and may be
  unreported or partial; the controlled-status taxonomy and the reserve
  percentage are design decisions. Budget must be enforced in the graph, not only
  in the CLI, so API callers get it too.
- **Suggested demo evidence:** Run with a low budget, show the warning status,
  the early stop of optional rounds, and the recorded total or an explicit
  "usage unavailable" note in the report.

### CAND-FR-03 — Structured Bull/Bear debate protocol

- **Shall statement:** The system shall conduct the Bull/Bear debate as a
  structured exchange in which each contribution states a claim, supporting
  evidence, a counterargument, a response, a confidence value, and any
  unresolved issue, with machine-readable per-round output.
- **Value:** Turns free-style prose into verifiable, reviewable structure -- a
  concrete example of structured agent collaboration.
- **Baseline status:** **NEW** (the debate exists but is free-text).
- **Repository evidence:**
  - `src/tradingagents/agents/researchers/bull_researcher.py` and
    `.../bear_researcher.py` build a prompt and call `llm.invoke(prompt)`,
    returning free text appended to `investment_debate_state`.
  - Structured output exists elsewhere (`src/tradingagents/agents/structured.py`,
    used by the managers/trader) but is **not** applied to the researchers.
- **Proposed fit criterion:** Each debate round emits a record matching a defined
  schema (claim, evidence, counterargument, response, confidence, unresolved
  issue). Every claim carries at least one evidence reference or is explicitly
  marked unsupported. Invalid structured output is retried once and then
  converted into a controlled error/review state rather than being silently
  accepted. The debate stops after the configured number of rounds.
- **Likely enforcing components:**
  `src/tradingagents/agents/researchers/bull_researcher.py`,
  `src/tradingagents/agents/researchers/bear_researcher.py`,
  `src/tradingagents/agents/structured.py`,
  `src/tradingagents/agents/schemas.py`,
  `src/tradingagents/graph/setup.py`.
- **Difficulty:** Medium.
- **Dependencies / overlaps:** Independent of the others; strengthens
  CAND-NFR-03 (reliability, invalid-JSON scenario) and supports CAND-NFR-04
  (traceability) and CAND-FR-05 (evidence-linked report) if evidence citation is
  shared. Risk of overlap with CAND-FR-05 if evidence citation is implemented
  only once.
- **Risks / design decisions:** Whether to keep a free-text fallback for
  providers without structured output; how much debate history to feed back
  without inflating tokens (interacts with CAND-FR-02).
- **Suggested demo evidence:** Show a debate round's structured record and a
  validation failure being caught and retried.

### CAND-FR-04 — Structured final-decision validation

- **Shall statement:** The system shall validate the final decision against a
  defined schema (a rating in the five-tier set, entry/stop levels as numeric
  prices, and the required fields present) before the result is accepted.
- **Value:** Prevents malformed or partial decisions from being treated as
  actionable output.
- **Baseline status:** **PARTIAL** (structured output + rating parsing exist;
  end-to-end decision validation as a gate does not).
- **Repository evidence:**
  - `src/tradingagents/agents/structured.py` binds structured output for the
    Portfolio Manager, Trader, and Research Manager, with a free-text fallback.
  - `src/tradingagents/agents/rating.py` parses the rating and returns
    `REVIEW` when it is absent/ambiguous; `parse_rating` defaults to `REVIEW`.
  - `src/tradingagents/agents/state.py` records `final_rating` (or `REVIEW`).
  - There is no single validation gate that rejects a decision whose numeric
    fields are malformed; the fallback path is free text.
- **Proposed fit criterion:** A final decision is accepted only if it carries a
  rating in `{Buy, Overweight, Hold, Underweight, Sell}` and any required price
  fields parse as finite numbers; otherwise the run records a non-actionable
  `REVIEW` result with a machine-readable reason and does not present a
  tradeable call.
- **Likely enforcing components:**
  `src/tradingagents/agents/structured.py`,
  `src/tradingagents/agents/rating.py`,
  `src/tradingagents/agents/schemas.py`,
  `src/tradingagents/agents/trader/trader.py`,
  `src/tradingagents/agents/managers/portfolio_manager.py`.
- **Difficulty:** Low–Medium.
- **Dependencies / overlaps:** Closely related to CAND-INV-01 (REVIEW invariant)
  and CAND-FR-03. Choose one owner across FR-04 / INV-01 to avoid duplication.
- **Risks / design decisions:** Decide whether validation is an accept/reject
  gate or a normalising step; keep compatibility with the existing free-text
  fallback.
- **Suggested demo evidence:** Feed a decision with a missing/mis-parsed price
  and show it converts to `REVIEW` with a reason instead of a tradeable call.

### CAND-FR-05 — Evidence-linked recommendation report

- **Shall statement:** The system shall produce a final recommendation in which
  each material claim is linked to the source data or agent report that supports
  it, and which includes a confidence value, main supporting and opposing
  factors, source identifiers/timestamps, and a "not investment advice" notice.
- **Value:** Strong, visible traceability -- good demo material and direct rubric
  evidence.
- **Baseline status:** **NEW** (reports exist; per-claim source linkage and the
  disclaimer do not).
- **Repository evidence:**
  - `src/tradingagents/reporting.py` and `src/tradingagents/report_html.py` render
    a report tree with a header and sections, but no per-claim source linkage.
  - No "not investment advice" notice was found in `src/`.
  - `src/tradingagents/graph/trading_graph.py`'s `run_settings()` already records
    what produced the run (models, analysts, rounds, vendors).
- **Proposed fit criterion:** In a sample report, every principal reason carries
  a source identifier traceable to an analyst/agent output or a dated data
  observation; reported market data includes its observation date; unsupported
  claims are labelled as unsupported; the report contains a "not investment
  advice" notice.
- **Likely enforcing components:**
  `src/tradingagents/reporting.py`,
  `src/tradingagents/report_html.py`,
  `src/tradingagents/agents/state.py`,
  `src/tradingagents/graph/trading_graph.py`.
- **Difficulty:** Medium.
- **Dependencies / overlaps:** Depends on the agents producing attributable
  statements; overlaps CAND-FR-03 (evidence in debate) and CAND-NFR-04
  (traceability). Coordinate one owner.
- **Risks / design decisions:** Defining "material claim" and how attribution is
  captured without a large token cost; whether linkage is structural (IDs) or
  prose.
- **Suggested demo evidence:** Walk through one report showing a recommendation
  traced back to analyst reports and dated data, ending with the disclaimer.

### CAND-FR-06 — Deterministic data-quality and recommendation gate

- **Shall statement:** Before issuing a final recommendation, the system shall
  check that required data is available, sufficiently current, and mutually
  consistent, and shall emit a defined status
  (`COMPLETED`, `COMPLETED_WITH_WARNINGS`, `INSUFFICIENT_DATA`,
  `AGENT_DISAGREEMENT_REQUIRES_REVIEW`) with a machine-readable reason.
- **Value:** A deterministic safety boundary around the LLM's output -- exactly
  the "AI output constrained by deterministic code" the course asks for.
- **Baseline status:** **PARTIAL** (per-vendor no-data handling and point-in-time
  bounds exist; an explicit final gate with these statuses does not).
- **Repository evidence:**
  - `src/tradingagents/dataflows/date_window.py` provides `as_of` /
    `as_of_window` and `withhold_*` helpers; `src/tradingagents/graph/trading_graph.py`
    validates the trade date is not in the future.
  - `src/tradingagents/dataflows/errors.py` and the vendor chain report
    unavailability rather than fabricating data.
  - No status enum like `INSUFFICIENT_DATA` /
    `AGENT_DISAGREEMENT_REQUIRES_REVIEW` exists for the final result.
- **Proposed fit criterion:** Missing mandatory data prevents an unconditional
  Buy/Sell (yields at least `INSUFFICIENT_DATA` or a warning); future-dated
  information relative to the analysis date is rejected; strong analyst
  disagreement yields `AGENT_DISAGREEMENT_REQUIRES_REVIEW`; each outcome carries
  a machine-readable reason code.
- **Likely enforcing components:**
  `src/tradingagents/graph/trading_graph.py`,
  `src/tradingagents/dataflows/date_window.py`,
  `src/tradingagents/dataflows/errors.py`,
  `src/tradingagents/agents/state.py`.
- **Difficulty:** Medium.
- **Dependencies / overlaps:** Builds on CAND-INV-02 (point-in-time). Complements
  CAND-NFR-03 (graceful failure). May overlap CAND-FR-04 acceptance gating.
- **Risks / design decisions:** Define the exact thresholds for "sufficiently
  current" and "strong disagreement"; ensure the gate is deterministic and
  unit-testable without live data.
- **Suggested demo evidence:** Force a missing-data and a disagreement scenario
  and show the distinct status codes in the report.

### CAND-FR-07 — Baseline-versus-enhanced comparison mode

- **Shall statement:** The system shall provide an evaluation command that runs
  or compares the baseline and enhanced configurations on the same
  ticker/analysis date and reports execution time, LLM calls, tokens, estimated
  cost (when pricing is configured), debate rounds, recommendation, confidence,
  and completion status, exported to JSON/CSV with percentage reductions.
- **Value:** Lets the demo show a measurable improvement rather than a claim.
- **Baseline status:** **NEW** (backtest exists; a baseline-vs-enhanced
  comparison command does not).
- **Repository evidence:**
  - `src/tradingagents/backtest.py` provides `iter_grid`, `run_backtest`, and
    `summarize`, and `src/cli/main.py` has a `backtest` command -- but it scores
    decisions over a date grid, not compares two configurations.
  - Token stats live only in the CLI (`src/cli/stats_handler.py`).
  - No `compare`/`--token-budget` style command exists in `src/cli/main.py`.
- **Proposed fit criterion:** Given the same ticker and cutoff date, the command
  runs both configurations, exports each run's metrics to JSON or CSV, computes
  percentage reductions in runtime and tokens, and reports unavailable provider
  usage as "unavailable" rather than an undisclosed estimate. Demonstrable on at
  least three stock/date cases.
- **Likely enforcing components:**
  `src/cli/main.py`, `src/tradingagents/backtest.py`,
  `src/tradingagents/graph/trading_graph.py`,
  `src/cli/stats_handler.py`.
- **Difficulty:** Medium.
- **Dependencies / overlaps:** Depends on CAND-FR-02 (token accounting) and
  CAND-FR-01 (a configuration to compare against the baseline). Provides the
  measurement harness for CAND-NFR-01 and CAND-NFR-02.
- **Risks / design decisions:** Comparability requires pinning model/provider/
  temperature; live calls cost money, so offline mocked comparison may be
  needed for tests.
- **Suggested demo evidence:** Run the comparison over three cases and show the
  exported table with token/runtime reductions.

### CAND-FR-08 — Reproducibility mode from recorded run settings

- **Shall statement:** The system shall be able to re-run an analysis using the
  exact settings recorded for a prior run (models, providers, analysts, rounds,
  temperature, data vendors), and shall record those settings in the report
  metadata.
- **Value:** Makes runs auditable and comparable; underpins fair comparison.
- **Baseline status:** **PARTIAL** (settings are recorded; faithful re-run from
  them is not a first-class feature).
- **Repository evidence:**
  - `src/tradingagents/graph/trading_graph.py`'s `run_settings()` returns an
    allowlist of what produced the run, used by `save_reports` and the state log.
  - `src/tradingagents/default_config.py` supports `temperature`,
    `TRADINGAGENTS_*` overrides, and per-tier providers, but there is no command
    to reload a recorded settings block into a new run.
- **Proposed fit criterion:** Given a recorded settings block from a prior run,
  the system starts a run with those settings applied and the new report's
  `run_settings` equals the source block (for the allowlisted keys); two runs
  launched from the same recorded settings share identical `run_settings`.
- **Likely enforcing components:**
  `src/tradingagents/graph/trading_graph.py`,
  `src/tradingagents/default_config.py`,
  `src/cli/main.py`.
- **Difficulty:** Low–Medium.
- **Dependencies / overlaps:** Complements CAND-FR-07 (comparison pins settings)
  and CAND-NFR-07 (observability). Note the README already warns LLM output is
  not bit-reproducible; this candidate reproduces *settings*, not output.
- **Risks / design decisions:** Settings must never include secrets/paths (the
  allowlist already enforces this); clarify that reproducibility is of
  configuration, not of sampled text.
- **Suggested demo evidence:** Export a run's settings, re-run from them, and
  show identical `run_settings` in both reports.

## 4. Non-functional-requirement candidates

Each NFR is stated as **metric + threshold + verification method**. Where no
baseline measurement exists, the threshold is **TBD** and the required baseline
experiment is described. **No numeric efficiency target may be adopted before a
baseline measurement exists.** This document does not put forward any specific
efficiency percentage as a goal; every such figure must come from a recorded
measurement first.

### CAND-NFR-01 — Token efficiency (quick profile vs baseline)

- **Metric:** Total LLM tokens per run (input + output), quick profile versus the
  baseline configuration on the same ticker/date.
- **Threshold:** **TBD.** The required baseline experiment: run the baseline and
  the quick profile over a fixed set of 3–5 stock/date cases, log total tokens
  per run (needs CAND-FR-02's accounting), and compute the median reduction.
  Only after that measurement may a numeric threshold be written. Until then, no
  reduction percentage may be assumed or advertised.
- **Comparison baseline:** The unmodified default configuration on the same
  ticker/date, same model/provider/temperature.
- **Verification method:** Automated comparison over the fixed case set using the
  comparison harness (CAND-FR-07); the logged token totals are the evidence.
- **Dependencies:** CAND-FR-01, CAND-FR-02, CAND-FR-07.
- **Offline testability:** The threshold check can run against mocked providers;
  the real numbers require live calls (see §8).

### CAND-NFR-02 — Performance (end-to-end runtime)

- **Metric:** Median end-to-end wall-clock time per run, quick profile versus
  baseline.
- **Threshold:** **TBD.** The required baseline experiment: measure start/finish
  timestamps over at least 3 repeated cases per configuration on the same
  provider, and compute the median difference. A fixed absolute target (e.g.
  "under 30 s") must not be set before API/network latency is measured.
- **Comparison baseline:** Baseline configuration, same ticker/date/provider.
- **Verification method:** Timestamp capture around each run via the comparison
  harness; report median and spread.
- **Dependencies:** CAND-FR-01, CAND-FR-07.
- **Offline testability:** Timing structure is unit-testable; true latency needs
  live calls.

### CAND-NFR-03 — Reliability and graceful failure

- **Metric:** Number of the controlled failure scenarios that terminate with a
  defined status and diagnostic message, with zero uncaught exceptions.
- **Threshold:** Scenario coverage (not a percentage): all of {provider timeout,
  agent returns invalid JSON, missing API key, stock data unavailable, token
  budget exhausted} produce a defined status and message without an uncaught
  exception.
- **Verification method:** One offline test per scenario using test doubles for
  the provider/data layer; assert the status code and message and the absence of
  an uncaught exception.
- **Baseline status:** **PARTIAL** -- there is graceful degradation in places
  (`src/tradingagents/dataflows/errors.py`, structured-output fallback in
  `src/tradingagents/agents/structured.py`), but not a uniform per-run completion
  status covering all five scenarios.
- **Dependencies:** CAND-FR-02 (budget-exhausted scenario), CAND-FR-06.
- **Offline testability:** Yes -- fully offline with test doubles.

### CAND-NFR-04 — Traceability

- **Metric:** Fraction of **formally defined material claims** in a sample report
  whose evidence source and producing agent can be identified.
- **Threshold:** The **baseline attribution percentage is TBD** -- it must be
  measured first: sample reports from N runs, list their material claims, and
  count how many are currently attributable. The **intended accepted-result rule**
  may then require that **100% of formally defined material claims resolve to
  evidence** (see CAND-INV-05), but that target is adopted only after the
  baseline is known and the definition of "material claim" is agreed. **Defining
  "material claim" is a design decision** left to the team; the metric is
  meaningless until that definition exists.
- **Verification method:** A checklist applied to sampled reports against the
  agreed "material claim" definition, plus (where feasible) a structural check
  that each recommendation references an analyst output and a dated observation.
- **Dependencies:** CAND-FR-05, CAND-INV-05, and the observability metadata in
  CAND-NFR-07.
- **Offline testability:** Partially -- structural checks offline; claim-by-claim
  audit is a human review step.

### CAND-NFR-05 — Maintainability and dependency boundaries

- **Metric:** Count of boundary violations (a component reading another
  component's internal state) plus pass/fail of the existing lint and test
  suites with the new components included.
- **Threshold:** Zero boundary violations among the new components; the lint
  command `ruff check .` passes; the offline suite passes; LLM/data dependencies
  are replaceable by test doubles in unit tests.
- **Verification method:** `ruff check .` (already in CI), the offline pytest
  suite, and import-layering assertions/structural tests for the new components.
- **Baseline status:** **PARTIAL** -- the repo is already modular
  (`src/tradingagents/{agents,graph,dataflows,memory,llm_clients}`) and linted,
  but there is no explicit invariant for the new components' boundaries.
- **Dependencies:** Applies to whichever candidates are chosen.
- **Offline testability:** Yes.

### CAND-NFR-06 — Security and secret redaction

- **Metric:** Number of configured secrets that appear unredacted in logs,
  reports, prompts, test fixtures, commits, or transcripts.
- **Threshold:** Zero (zero-tolerance). A test asserts that logs redact a known
  configured API key; a secret scan runs on every PR and blocks merge on failure;
  `.env` is git-ignored.
- **Verification method:** An offline test around `get_scrubbed` in
  `src/tradingagents/dataflows/net.py` (which already keeps query-param keys out
  of `requests` errors) extended to log/report rendering; plus a secret-scan CI
  gate (currently absent -- see §8 note on tooling).
- **Baseline status:** **PARTIAL** -- `get_scrubbed` exists and is tested
  (`test/offline/test_get_scrubbed.py`); no repo-wide secret-scan gate exists in
  `.github/workflows/ci.yml`.
- **Dependencies:** None; pairs well with any candidate.
- **Offline testability:** Yes (redaction test is offline; scanning is CI).

### CAND-NFR-07 — Observability metadata

- **Metric:** Set of required fields present in every run's structured metadata
  (profile, models/providers, analysts, rounds, data vendors, token totals,
  status).
- **Threshold:** All required fields present and correctly typed in every
  completed run; absent/unavailable values are labelled, not omitted.
- **Verification method:** An offline test that asserts the metadata schema on a
  completed (mocked) run; extend `run_settings()` and the report header.
- **Baseline status:** **PARTIAL** -- `run_settings()` in
  `src/tradingagents/graph/trading_graph.py` records a subset (models, analysts,
  rounds, vendors) but not profile, token totals, or status.
- **Dependencies:** CAND-FR-01, CAND-FR-02, CAND-FR-06.
- **Offline testability:** Yes.

### CAND-NFR-08 — Offline testability

- **Metric:** Fraction of the new feature's tests that run with no network access
  and pass in any order.
- **Threshold:** 100% of the new features' deterministic tests live under
  `test/offline/`, use no network, and pass under the existing
  `-m "not integration"` selection in any order.
- **Verification method:** Run the offline suite (`pytest` with the repo's
  default selection) in isolation and in random order; any network use fails a
  dedicated guard.
- **Baseline status:** **EXISTING-UNVERIFIED/PARTIAL** -- the repo already
  separates `test/offline` and `test/live` and offlines the suite by default
  (`pyproject.toml` `testpaths`, `-m "not integration"`, and README claims
  network-free offline tests), but there is no explicit order-independence
  guarantee for new work.
- **Dependencies:** Applies to every candidate.
- **Offline testability:** This *is* the offline-testability requirement.

## 5. Invariant candidates

Invariants are zero-tolerance rules. For each: statement, zero-tolerance fit
criterion, enforcing component, negative test, operational fallback, and current
status.

**How to read the "current status" of each invariant.** An invariant marked
**EXISTING** is already implemented in the baseline; a candidate owner would
perform **formalisation and verification work** (write it into the invariant
register and trace matrix, and add or strengthen the negative test that fails
when it is violated) rather than build new functionality. An invariant marked
**PARTIAL** or **NEW/CLAIMED-ONLY** still needs implementation work. The
classification is stated explicitly on every invariant below so existing
behaviour is never mistaken for a new enhancement.

### CAND-INV-01 — Invalid/contradictory ratings produce REVIEW

- **Invariant statement:** A decision with an invalid, missing, contradictory, or
  unreadable rating shall never be presented as a tradeable position.
- **Zero-tolerance fit criterion:** For any final decision whose rating cannot be
  resolved to exactly one of `{Buy, Overweight, Hold, Underweight, Sell}`, the
  recorded `final_rating` equals `REVIEW`, in every case, with no exception.
- **Likely enforcing component:** `src/tradingagents/agents/rating.py`
  (`RATING_REVIEW`, `parse_rating`, `is_review`).
- **Negative test:** Feed text with no rating, two conflicting ratings, and a
  fullwidth-colon rating; assert each yields `REVIEW`
  (see `test/offline/test_rating_integrity.py`).
- **Operational fallback:** Mark the run non-actionable; surface `REVIEW` and a
  re-run/human-review notice; never substitute Hold.
- **Current status:** **EXISTING** (claimed and tested). This is **formalisation
  and verification work, not new functionality**: a candidate owner would
  formalise it as an invariant row in the registry/trace matrix and confirm the
  negative test rather than build it.

### CAND-INV-02 — Point-in-time data integrity

- **Invariant statement:** A run dated *d* shall never receive data dated
  after *d*.
- **Zero-tolerance fit criterion:** For a run with analysis date *d*, no data
  observation with a timestamp later than *d* is served to any agent.
- **Likely enforcing components:** `src/tradingagents/dataflows/date_window.py`
  (`as_of`, `as_of_window`, `withhold_*`),
  `src/tradingagents/graph/trading_graph.py` (`_validate_trade_date` rejects
  future dates).
- **Negative test:** Request a window ending after *d* for a historical run and
  assert the served end is clamped to *d*; assert a future `trade_date` raises
  (see `test/offline/test_date_boundaries.py`,
  `test/offline/test_tool_date_enforcement.py`,
  `test/offline/test_memory_pointintime.py`).
- **Operational fallback:** Clamp to *d* and emit a point-in-time notice; if the
  vendor cannot honour the bound, withhold and label the data as unavailable.
- **Current status:** **EXISTING** (implemented and tested for the dated paths).
  This is **formalisation and verification work, not new functionality**: a
  candidate would prove coverage is complete across every vendor and add the
  trace/invariant row.

### CAND-INV-03 — Maximum tool-round enforcement

- **Invariant statement:** An analyst shall never exceed the configured maximum
  number of tool-call rounds.
- **Zero-tolerance fit criterion:** For every analyst, the number of tool-call
  rounds in a run is `<= max_tool_rounds`.
- **Likely enforcing component:** `src/tradingagents/graph/setup.py`
  (`_analyst_graph`, `more_or_wrap_up`, `wrap_up`).
- **Negative test:** A stub model that keeps requesting tools stops at
  `max_tool_rounds` and produces a report instead of hitting the recursion limit.
- **Operational fallback:** Force the wrap-up turn and end the analyst with what
  it has.
- **Current status:** **EXISTING** (implemented). This is **formalisation and
  verification work, not new functionality**: verify a dedicated negative test
  exists or add one.

### CAND-INV-04 — No silent failure of mandatory agents

- **Invariant statement:** A run shall not silently omit a mandatory agent's
  contribution; a failed mandatory agent ends in a defined error/warning status.
- **Zero-tolerance fit criterion:** If a mandatory agent fails, the run never
  reports `COMPLETED` as if it succeeded; it reports a defined error/warning
  status naming the agent.
- **Likely enforcing components:** `src/tradingagents/graph/setup.py`,
  `src/tradingagents/graph/trading_graph.py`,
  `src/tradingagents/agents/state.py`.
- **Negative test:** Force one mandatory analyst to raise and assert the run ends
  with a non-success status naming it (offline, with a test double).
- **Operational fallback:** Emit a defined status and diagnostic; do not present
  a complete-looking report.
- **Current status:** **PARTIAL** -- related to CAND-FR-06/CAND-NFR-03; the
  uniform status enforcement does not exist yet.

### CAND-INV-05 — No untraceable material claim in an accepted result

- **Invariant statement:** An accepted recommendation shall contain no material
  claim that cannot be traced to a source (agent output or dated data).
- **Zero-tolerance fit criterion:** In every accepted result, each material claim
  carries a resolvable source reference; an untraceable material claim prevents
  acceptance (downgrades the status).
- **Likely enforcing components:** `src/tradingagents/reporting.py`,
  `src/tradingagents/graph/trading_graph.py`.
- **Negative test:** An accepted result containing a claim with no source is
  rejected/downgraded by the checker.
- **Operational fallback:** Downgrade to a warning/review status and label the
  claim as unsupported.
- **Current status:** **NEW/CLAIMED-ONLY** -- depends on CAND-FR-05; not present
  today.

### CAND-INV-06 — No credential leakage

- **Invariant statement:** A credential shall never appear in logs, reports,
  prompts, test fixtures, commits, or transcripts.
- **Zero-tolerance fit criterion:** Zero occurrences of any configured secret in
  any emitted artifact; a redaction test proves a known key is masked.
- **Likely enforcing components:** `src/tradingagents/dataflows/net.py`
  (`get_scrubbed`), report/log renderers, CI secret scan.
- **Negative test:** Configure a dummy key, trigger an error path, assert the key
  is absent from the captured log/error
  (`test/offline/test_get_scrubbed.py`).
- **Operational fallback:** Redact and re-emit the error without the secret; block
  the PR if a scan finds a secret.
- **Current status:** **PARTIAL** -- `get_scrubbed` covers query-param keys on the
  data path; repo-wide coverage and a CI secret-scan gate are absent.

### CAND-INV-07 — Deterministic ticker resolution

- **Invariant statement:** The analysed company shall be resolved
  deterministically from the ticker before any agent runs.
- **Zero-tolerance fit criterion:** The same ticker always yields the same
  resolved instrument identity, independent of run order or agent behaviour.
- **Likely enforcing components:** `src/tradingagents/dataflows/symbols.py`,
  `src/tradingagents/agents/context.py`
  (`resolve_instrument_identity`, `build_instrument_context`),
  `src/tradingagents/graph/trading_graph.py`.
- **Negative test:** Resolve the same ticker repeatedly and via different entry
  points and assert identical identity
  (see `test/offline/test_symbols.py`,
  `test/offline/test_symbol_normalization_paths.py`).
- **Operational fallback:** Reject an unresolvable ticker before the run starts
  with a clear error.
- **Current status:** **EXISTING** (implemented and tested). This is
  **formalisation and verification work, not new functionality**: write it into
  the registry/trace matrix and keep the negative test.

## 6. Candidate comparison matrix

Legend: Difficulty L/M/H; Offline testability and Demo visibility rated by
effort to obtain. "Primary?" = suitable as one person's primary requirement.

| Candidate | Classification | Product value | Rubric alignment | Difficulty | Offline testability | Demo visibility | Dependencies | Baseline status | Primary? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CAND-FR-01 Profiles | Functional | High | Cost control, architecture | L–M | High | High | None | PARTIAL | Yes |
| CAND-FR-02 Token budget | Functional | High | Token reduction, safety | M | Medium | High | FR-01/NFR-07 | NEW | Yes |
| CAND-FR-03 Structured debate | Functional | High | Structured collaboration | M | Medium | Medium | NFR-03 | NEW | Yes |
| CAND-FR-04 Decision validation | Functional | Medium | Deterministic safety | L–M | High | Medium | INV-01 | PARTIAL | Maybe |
| CAND-FR-05 Evidence-linked report | Functional | High | Traceability | M | Medium | High | FR-03/NFR-04 | NEW | Yes |
| CAND-FR-06 Data-quality gate | Functional | High | Safety boundary, production | M | High | High | INV-02/NFR-02 | PARTIAL | Yes |
| CAND-FR-07 Comparison mode | Functional | Medium | Measurable improvement | M | Medium | High | FR-01/FR-02 | NEW | Yes |
| CAND-FR-08 Reproducibility | Functional | Medium | Auditability | L–M | High | Low–Med | NFR-07 | PARTIAL | Maybe |
| CAND-NFR-01 Token efficiency | Quality/cost | High | Token reduction | M | Medium | High | FR-01/02/07 | TBD | Maybe (pairs) |
| CAND-NFR-02 Performance | Performance | Medium | Efficiency | M | Medium | Medium | FR-01/07 | TBD | Maybe |
| CAND-NFR-03 Reliability/failure | Quality | High | Production-grade | M | High | Medium | FR-02/FR-06 | PARTIAL | Yes |
| CAND-NFR-04 Traceability | Quality | High | Traceability | M | Partial | High | FR-05/NFR-07 | TBD | Maybe (pairs) |
| CAND-NFR-05 Maintainability | Maintainability | Medium | Low coupling | L | High | Low | Any | PARTIAL | No (cross-cutting) |
| CAND-NFR-06 Secret redaction | Security | High | Security gate | M | High | Low | None | PARTIAL | Yes |
| CAND-NFR-07 Observability | Quality | Medium | ADD, traceability | L–M | High | Medium | FR-01/02/06 | PARTIAL | Maybe |
| CAND-NFR-08 Offline testability | Quality | Medium | Verification | L | High | Low | Any | PARTIAL | No (cross-cutting) |
| CAND-INV-01 REVIEW | Invariant | High | Safety | L | High | Low | — | EXISTING | No (formalise) |
| CAND-INV-02 Point-in-time | Invariant | High | Safety, traceability | M | High | Low | — | EXISTING | Maybe (formalise) |
| CAND-INV-03 Tool rounds | Invariant | Medium | Safety | L | High | Low | — | EXISTING | No (formalise) |
| CAND-INV-04 No silent failure | Invariant | High | Production | M | High | Medium | FR-06/NFR-03 | PARTIAL | Maybe |
| CAND-INV-05 No untraceable claim | Invariant | High | Traceability | M | Medium | High | FR-05 | NEW | Maybe |
| CAND-INV-06 No secret leak | Invariant | High | Security | M | High | Low | NFR-06 | PARTIAL | Maybe |
| CAND-INV-07 Ticker resolution | Invariant | Medium | Determinism | L | High | Low | — | EXISTING | No (formalise) |

## 7. Suggested coherent six-person packages

Neither package assigns requirements to named members, and neither marks any
requirement as approved or selected. They are starting points for discussion.

### Package A — Balanced (recommended default)

Six primary functional requirements, one per member, each with a paired
quality/invariant concern:

1. CAND-FR-01 Analysis profiles (paired NFR: CAND-NFR-02 Performance).
2. CAND-FR-02 Token budget (paired NFR: CAND-NFR-01 Token efficiency).
3. CAND-FR-03 Structured debate (paired NFR: CAND-NFR-03 Reliability).
4. CAND-FR-05 Evidence-linked report (paired NFR: CAND-NFR-04 Traceability).
5. CAND-FR-06 Data-quality gate (paired invariant: CAND-INV-02 Point-in-time,
   plus CAND-INV-04).
6. CAND-FR-07 Comparison mode (paired NFR: CAND-NFR-05 Maintainability / CAND-NFR-07
   Observability).

Invariants CAND-INV-01, CAND-INV-03, CAND-INV-06, CAND-INV-07 are formalised
across the package rather than owned individually. This package maximises rubric
alignment (token reduction, structured collaboration, safety boundary,
traceability, measurable demo, gates) but has the most coordination.

### Package B — Lower-risk

Prefers candidates with the strongest existing support so effort goes into
formalisation, verification, and evidence rather than large new subsystems:

1. CAND-FR-01 Analysis profiles (strong scaffolding already present).
2. CAND-FR-04 Decision validation (builds on existing structured output +
   `rating.py`).
3. CAND-FR-08 Reproducibility (builds on existing `run_settings()`).
4. CAND-NFR-03 Reliability/failure (mostly test-double work).
5. CAND-NFR-06 / CAND-INV-06 Secret redaction (extends existing `get_scrubbed`
   plus a CI scan).
6. CAND-NFR-07 Observability (extends `run_settings()`).

This package is easier to land and verify but exposes less visible product change
and less of the headline "token reduction" story; it relies on CAND-FR-01 plus
CAND-NFR-07 to carry the efficiency narrative.

## 8. Baseline measurements still needed

Every numeric threshold that is currently **TBD**, with the experiment that must
precede it.

| Threshold | What must be measured | Controlled variables | Expected output | Live/paid calls? |
| --- | --- | --- | --- | --- |
| CAND-NFR-01 token reduction % | Total tokens (in+out) per run, baseline vs quick, 3–5 fixed cases | Same provider, models, temperature, analysts, vendors, dates | Per case: tokens_in/out, total; median % reduction | **Yes** (real usage); mock harness first |
| CAND-NFR-02 runtime reduction % | Wall-clock per run, baseline vs quick, >=3 repeats | Same provider/network, models, temperature; note time of day | Per case/repeat: seconds; median and spread | **Yes**; timing testable offline |
| CAND-NFR-04 traceability fraction | Attributable fraction of material claims in sampled reports | Fixed sample of N reports from defined cases | Per report: claims, # attributable, fraction | Partial: fixtures offline; real runs live |
| Token-budget policy constants (CAND-FR-02) | Token share of final-report phase vs earlier phases (reserve sizing) | Same provider/model; several tickers | Distribution by phase; chosen reserve % | **Yes** to characterise |
| "Strong analyst disagreement" definition (CAND-FR-06) | Distribution of agreement/disagreement signals over sample runs | Fixed ticker/date set | Histogram; chosen deterministic threshold | **Yes** to calibrate |
| Secret-scan tooling choice (CAND-NFR-06) | N/A (tooling decision) | — | Chosen tool + CI job; repo scan | No |

Notes for the team:

- Do **not** write a numeric token or runtime threshold into the authoritative
  registry until the corresponding experiment above has produced a baseline. Use
  `TBD` in the registry until then, with a link to the recorded measurement.
- The comparison baseline for any cost or performance metric is the
  **unmodified default configuration** run on the **same ticker/date, same
  provider, same model IDs, and same temperature** as the enhanced configuration.
- Measurements that require live provider calls should be recorded once and
  reused, so the team does not repeatedly spend tokens re-measuring.
