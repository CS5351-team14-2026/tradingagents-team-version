<!-- Coding agents start from AGENTS.md + Prompt.md. Course blocking gates are
     enforced by CI; the checklist below mirrors them for reviewers. -->

## Summary

## Requirements touched
<!-- REQ-TA-... IDs from docs/req/requirements.yaml, or "none (governance/docs only)" -->

## Test plan
<!-- REQUIRED when this PR touches src/ or test/ (course blocking gate 1):
     1. Open a test-plan issue describing the tests to be written (fit criteria
        covered, negative tests per invariant).
     2. Have a teammate review it and add the `test-approved` label BEFORE
        implementation starts.
     3. Reference it here as: test-plan: #<issue number>
     Delete this section if the PR does not touch src/ or test/. -->

## Agent sessions
<!-- Course blocking gate 6: if this PR touches src/ or prompts/, every agent
     session behind it gets an entry in docs/ai-use-log.yaml. List the sessions
     and note where human interventions happened (transcripts/). -->

- [ ] docs/ai-use-log.yaml updated for every agent session behind this change (n/a if docs/CI-only)

## Review memo
<!-- Link the memo section in docs/review-memo.md that covers this PR -->

## Reviewer checklist (course gates)
- [ ] Schema gate: registry changes (if any) validate (CI enforces)
- [ ] Regression: full offline suite green, zero regressions (CI enforces)
- [ ] Test plan approved before implementation (CI enforces when src/test touched)
- [ ] Safe-path changes (if any) carry an ADR reference and human review
- [ ] Structural constraints SC-1..SC-5 respected (docs/code-governance/)
