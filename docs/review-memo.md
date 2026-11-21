# Review memos — one per pull request (deliverable D4, project.pdf p6)

Format for every memo (append below, newest last):

```
## MEMO-NNNN — PR #<number> <title>

- Spec alignment: <does the diff do what the cited REQ-TA-IDs say?>
- Architecture alignment: <conforms to blueprint/ADRs/structural constraints?>
- Code & test quality: <incl. negative tests, test IDs cited>
- Ops metadata: <ai-use log entries, trace rows, docs updated?>
- Security & efficiency: <secrets, permissions, token/step cost of the change>
- Verdict: APPROVE | CHANGES REQUIRED | REJECT (reviewer, date)
```

---

## MEMO-0001 — this PR: "governance: foundational blocking gates + code-governance documents"

- Spec alignment: sets up D1 registry path (`docs/req/`), registry converted
  from the candidate catalogue with all entries `status=candidate` (no
  requirement is claimed as committed), `req-schema.json`, gate 3/6/1 CI jobs,
  advisory dependency audit, D3 documents (`AGENTS.md`, `Prompt.md`,
  permission model), D4 records (this file, debt register, bug diary).
  Consistent with project.pdf p5–p10.
- Architecture alignment: no product code touched; module layout untouched;
  constraints recorded for future slices (SC-1..SC-5).
- Code & test quality: two CI validator scripts, ruff-clean, no product
  runtime impact; gates exercise real diffs (no placeholder pass-throughs
  except the documented advisory/warning modes tied to debt entries).
- Ops metadata: AI-use log intentionally not yet created (team has not
  formally kicked off); gate 6 will bite at kickoff. Rules files left empty
  for human authorship per course human-only rule.
- Security & efficiency: no secrets; no runtime dependency added; advisory
  audit adds CI minutes only.
- Verdict: CHANGES REQUIRED until human reviewers confirm — specifically the
  `.opencode/rules.md` / `.agent/rules.md` human-authorship plan and the
  registry conversion (statuses/priorities are pre-draft).

---

## MEMO-0002 — this PR: "docs(req): governance requirements (7 types complete) + gate adaptation"

- Spec alignment: adds REQ-TA-GOV-001..005 so all seven requirement types of
  project.pdf p5 D1 are represented; every entry `status=candidate`, anchored
  to code located by the 2026-11-13 source analysis (no invented components).
  Adapts governance config to the current state per team decisions: safety-
  critical path list grounded (permissions.jsonc, DEBT-004), pip-audit stays
  advisory until the 2026-11-21 feature freeze (DEBT-002), gate-4 trigger
  paths recorded (DEBT-003). AI-use log intentionally still absent — the
  team has not formally kicked off (DEBT-008 open; gate 6 stays in warning
  mode until then).
- Architecture alignment: no product code touched; GOV entries only record
  existing mechanisms (prompt surfaces, key registry, run_settings allowlist,
  vendor-chain policy, checkpoint signature).
- Code & test quality: schema gate re-validated locally against the grown
  registry (28 entries); no runtime code changed.
- Ops metadata: registry header bumped to v0.3 with provenance; CHANGELOG
  updated.
- Security & efficiency: no secrets; no new dependencies; CI unchanged.
- Verdict: APPROVE pending human reviewer confirmation of the GOV statements
  and priorities (pre-draft, S1 will finalize).

## 2026-11-21 — FR-007 / PERF-001 local final verification review

Reviewer: Codex automated self-review; human PR approval remains required.
Scope: comparison telemetry and per-run recovery, plus human-authorized minimal
integration corrections (PM JSON prompt, existing three-claims bound, canonical
usage before persistence, typed confidence). Architecture: ADR-001/003/004 and
proposed ADR-007. Price/strict-NaN/claim acceptance rules remain fail-closed;
malformed claims are not trimmed. No frozen/rules/credential files, dependency
metadata or Git state changed.

Verification: full offline 1905 passed, 1 optional AWS skipped, 1 live deselected,
100 subtests; full lint passed. Earlier failing ledger-call-count regression was
fixed before the final cohort. Source and inputs freeze for real measurements;
completed measurements are never repeated to obtain a favorable result, failed
attempts remain visible. The final 18-run cohort has been independently checked and archived with source, settings, CSV/JSON and canonical metadata verification. All rejected reports remain visible.

Verdict: **APPROVE for manual PR submission (automated self-review only)**. Final real data and documentation are archived under docs/evidence/perf001-2026-11-21-final/. Human review/CI/target adoption remain pending; rejected investment reports are not approved.
This is not a human approval, a statement about remote CI, or an adoption of a
numeric performance threshold. Detailed review and prior failures stay in the
sibling local logs; only sanitized measurements and minimal governance records
are included in the eventual PR.

---

## MEMO-0003 — PR #61 "batch: FR-002 + FR-004 + FR-007 + FR-008 + QR-001 + QR-004 + QR-005 (2026-11-21)"

- Spec alignment: FR-007/PERF-001 eval comparison (#34, plan #39); QR-004 structured run record (#38, plan #37); FR-002 token budget with optional-call enforcement (#48, plan #46); FR-008 settings replay (#49, plan #44); FR-004 final-decision price validation + review enforcement (#52/#54/#57, plan #32); QR-005 offline isolation + seeded order (#53, plan #32); QR-001 controlled failure codes + run-record failure block (#60, plan #58); SEC-001 unfreeze/claim docs-only (#51). All plans test-approved before merge (gate 1).
- Architecture alignment: ADR-004 (token budget) lands with FR-002; components map to existing trace-matrix rows; QR-003 layering/structural tests pass unchanged; the evaluation layer reads the public profile resolver instead of duplicating settings.
- Code & test quality: full offline suite green on integration at 306c996 (run 44864318356, py3.11–3.14 + tz, clean-install, ruff, gates 1/3/6); negative tests in place for budget refusal at N, invented statuses/limits, untraceable claims, invalid structured output, and controlled failure paths; duplicate-delivery and concurrency covered for the budget ledger.
- Ops metadata: ai-use-log updated in every feature PR (gate 6); trace rows in docs/architecture/trace-matrix.md; PERF-001/COST-001 thresholds remain TBD pending the live comparison — tracked in issue #62.
- Security & efficiency: no credentials or local paths in any recorded artifact (QR-004 allowlist + FR-008 rejection tests); FR-002 caps optional LLM calls at the budget; the 18-run live comparison cost is acknowledged and deferred to #62.
- Verdict: APPROVE (Kwok-Kwok248, 2026-11-21)

## 2026-11-21 — evaluation / current integration merge reconciliation

Reviewer: Codex automated self-review, pending human PR review.

- Both the local final-experiment memo and the team's MEMO-0003 were retained.
- Graph terminal paths preserve ADR-005 failure classification and REVIEW rules,
  while attaching the shared usage ledger before failed/successful persistence.
- FR-007 reads public canonical lifecycle/failure metadata and returned
  run_failure. Controlled failures cannot count as speedups; ordinary claim
  rejection alone stays separate. No raw failure diagnostic is copied.
- The proposed evaluation ADR is numbered ADR-007 to avoid collision with the
  team's ADR-005 controlled failures and ADR-006 secret redaction.
- Verification: 39 focused evaluation/recovery/failure cases passed; full merged
  offline suite **1985 passed, 1 optional AWS skipped, 1 live deselected, 100
  subtests**; full ruff, registry and AI-log gates passed. Loopback tests required
  OS socket permission and NO_PROXY/no_proxy=127.0.0.1,localhost: the test proxy
  previously returned HTTP502. No unrelated login code was changed or tests skipped.
- Scope check: other teammates' incoming requirement values and AI-log entries
  preserved; original live-evidence checksums unchanged. The earlier 18-run
  source cohort remains historical evidence, not a live measurement of this
  newly merged source. No new paid model runs and no Git commands by the agent.
- Verdict: **APPROVE for manual merge commit and PR submission (automated
  self-review only)**. Remote CI, human review, the common-output-cap protocol
  and numerical target proposal still require the team's decision.
