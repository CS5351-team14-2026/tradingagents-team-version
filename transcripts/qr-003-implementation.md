# Transcript — REQ-TA-QR-003 component-boundary enforcement

- **Requirement:** REQ-TA-QR-003 (quality; maintainability and dependency boundaries)
- **Test plan:** #25 (`test-approved`; course gate 1)
- **Branch:** `feat/qr-003-component-boundaries`
- **Agent session:** OpenCode, `CS5351/DeepSeek-V4-Flash`
  (`custom-foundry/CS5351/DeepSeek-V4-Flash`), 2026-11-16
- **AI-use log entry:** `AI-2026-11-16-001` in `docs/ai-use-log.yaml`
- **Workflow:** `Prompt.md` (understand → plan → stop → staged build with a human
  gate at every stage → self-verify → record).

This file records the actual implementation and the human review gates of the
session behind this PR. It is not a fabricated replay: each stage below names the
review that changed it, matching the conversation in which the human redirected
or approved the work.

## Scope

The only product code touched is the offline test layer:

- `test/offline/test_layering.py` — extends the existing vendor-layering guard
  with a structural boundary check over the five components
  (`agents`, `graph`, `dataflows`, `memory`, `llm_clients`).
- `test/offline/test_graph_end_to_end.py` — asserts the scripted LLM double is
  actually exercised by a full graph run (`assert model.calls`).

The structural check detects **statically parseable** cross-component private
imports and alias reads (from the AST): absolute/relative `from … import _x`,
`import a.b._m`, private names taken out of a private module, and `alias._x` /
package-alias `df.config._x` / full-path `a.b.c._x` attribute reads resolved to
their import. It does not evaluate dynamic access (e.g. `getattr`, `importlib`,
values passed around at runtime); those are outside its static reach.

`REQ-TA-QR-003` is a test/verification requirement, so no runtime module was
changed; the baseline (v0.7.1 + src-layout, commit `2438f28`) is extended, not
replaced.

## Stage 1 — component-boundary structural check (iterated over review rounds)

The check walks the five components and flags any statically parseable
cross-component private import or alias read, while allowing public calls and
own-component private use. It was refined across several human review rounds;
each round is a recorded intervention. The test counts below are the *directed*
runs of `test/offline/test_layering.py` in the review environment for that round;
the authoritative full-suite result is the post-PR-#27 Windows run recorded under
Evidence.

1. **First draft.** AST scan: absolute/relative `from ... import _x` and
   `alias._x` reads; failure message names the source file and the crossing
   dependency; new modules auto-scanned via `rglob`. Human review caught that the
   two path-based assertions were not cross-platform and that the relative-import
   base was off by one. → Fixed `_resolve_from`, added `_names_path`.
2. **Second round (Windows directed run: 11 passed / 2 failed).** The two failing
   path assertions were made OS-neutral; alias resolution was made per-file (a
   same-named alias in another file no longer leaks); function-local imports were
   scoped to their function; a nested function's parameter no longer shadowed an
   outer read; `df.config._merge` leftmost-name shadowing was handled; and a plain
   `import a.b.c` followed by `a.b.c._merge` was covered. → 17 tests.
3. **Third round (scope resolution).** Human reported three reproduced cases;
   the fix replaced the static alias map with scope-chain resolution and added
   regressions for function-local import + same-function private read (now
   proves interception, not just public calls), no leak into other functions,
   module-alias reassigned as a local, and an inner closure reading an outer
   parameter.
4. **Fourth round (statement order).** Same-function ordered statements had to
   resolve by read position: import → local assign → read passes; assign → import
   → read fails; read → reassign → read reports only the first. Implemented with
   position-aware binding events.
5. **Fifth round (assignment RHS + private modules).** An assignment's
   right-hand side must resolve against the *previous* binding
   (`cfg = cfg._merge({}, {})` → 1); private-module imports across components
   (public name taken from a private module, and `import a.b._secret`) were added.
6. **Sixth round (AST end position).** The `_AFTER_LINE` sentinel was replaced by
   the owning statement's real end position, fixing multi-line RHS calls and a
   same-line following statement; two regressions added.
7. **Seventh round (`for`/`with` timing).** Targets bind after the header
   expression, before the block: `for cfg in cfg._items():` and
   `with cfg._open() as cfg:` each report only the header private call, while the
   block reads of the new local object pass. A SIM102 in `_header_end` was fixed.

Each round was verified with the *directed* structural test
(`test/offline/test_layering.py` in isolation) and `ruff check .`; the human gated
each transition. The full offline suite was run on the Windows validation
environment after these rounds and PR #27 were synchronised (see Evidence).

## Stage 2 — LLM-double assertion in the full-graph test

`test_a_full_run_reaches_a_logged_decision` kept the `ScriptedModel` in a
variable and added `assert model.calls` after `graph.propagate(...)`, proving the
graph invokes the LLM test double (the fixed market-data double and report
assertions were already present and preserved). Parametrized over both output
modes (`free-text`, `structured`). Reviewed and approved.

## Evidence

Directed checks (run in the review rounds; scoped to the touched files):

- `test/offline/test_layering.py`: 30 tests pass (component boundaries + the
  retained `test_vendor_libraries_are_imported_only_by_the_data_layer`); revised
  incrementally per round (round 2: 17, … through 30 by the last Stage 1 round).
- `test/offline/test_graph_end_to_end.py::test_a_full_run_reaches_a_logged_decision`:
  both `free-text` and `structured` pass (asserting `model.calls` non-empty,
  market-data double called, report produced).
- `ruff check .`: clean on the review environment each round.

Full-suite result (authoritative, Windows validation environment):

- After synchronising PR #27 (FR-005) into the branch and completing Stages 1–2,
  the full offline suite passed: **1483 passed**. Windows `ruff` and both output
  modes were green.
- Traceability: `docs/architecture/trace-matrix.md` (QR-003 section).

## Human decisions recorded

- Approved the plan (S1 approach) and each Stage 1 refinement round before code
  moved on.
- Approved Stage 2 after the Windows ruff + full-suite validation.
- Confirmed `test-plan: #25` stays in the PR body (gate 1); the test-plan issue
  carries the `test-approved` label.
