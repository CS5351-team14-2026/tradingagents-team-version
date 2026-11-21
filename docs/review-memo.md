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
proposed ADR-005. Price/strict-NaN/claim acceptance rules remain fail-closed;
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
