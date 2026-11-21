# Project covenant — engineering principles

This is the project's covenant: rules that outlive any single task. They are
human-authored and bind every change, including changes made by coding agents.
`.opencode/rules.md` defines how an agent behaves during a session; this file
defines what the team considers an acceptable change.

## 1. Abstraction limits

- A new abstraction is allowed only at an existing module seam
  (`docs/code-governance/structural-constraints.md` SC-1). One level of
  indirection per new concept; no generic frameworks; extend an existing
  function before introducing a new layer.
- Every new module or function cites the ADR and the requirement/invariant it
  implements.

## 2. Dependency constraints

- New runtime dependencies require an ADR and human approval.
- Vendor SDKs live only in `dataflows/vendors/**`; provider clients only in
  `llm_clients/**`; no cross-component private imports (REQ-TA-QR-003).
- New work extends the v0.7.1 baseline; replacing existing behaviour needs an
  ADR.

## 3. Test independence

- Every feature ships at least one negative test that fails when the behaviour
  regresses.
- Tests cite the requirement/invariant ID they verify, run offline and
  network-free, are order-independent, and never depend on another test's
  state.
- Any test change that weakens an assertion must be justified in the review
  memo; tests are never edited merely to make a change pass.

## 4. Safety-critical changes

- Changes to `agents/rating.py`, `dataflows/{date_window,errors,net,symbols}.py`
  and `llm_clients/api_key_env.py` require an architecture decision (ADR) and
  human approval before merge.
- An agent may never approve its own safety-relevant change; the reviewer must
  be a human other than the author.

## 5. Context freshness

- After any requirement change, `AGENTS.md`, `architecture-blueprint.md` and
  this covenant are updated within one sprint (7 days); the registry is updated
  in the same change.
- A stale rule or stale architecture document is a defect, not documentation
  debt.

## 6. Definition of done

A change is done when: the registry status is accurate, its fit-criterion test
exists and passes, the trace row and the AI-use log are updated, `ruff` and the
full offline suite are green, and a human has reviewed the diff.
