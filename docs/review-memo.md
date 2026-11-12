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
