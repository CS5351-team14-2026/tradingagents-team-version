# Review memos

> Deliverable D4 (project.pdf p6): one memo per pull request, covering spec
> alignment, architecture alignment, code and test quality, operational
> metadata, and security/efficiency, ending in APPROVE / CHANGES REQUIRED /
> REJECT.

> **Provenance.** MEMO-0001..0003 were written while the corresponding PRs
> were open. MEMO-0004 onward are **retrospective memos compiled on
> 2026-11-21 from the merged-PR record** (title, diff statistics, CI
> outcome, requirement and ADR mapping). They do not claim a contemporaneous
> human review that did not happen; every PR listed here was merged after CI
> passed, and the record is the source of truth.

## MEMO-0001 — PR #6 "governance: foundational blocking gates + code-governance documents"

- Spec: establishes `docs/req/` registry path, converts the candidate catalogue into `requirements.yaml` (all entries `status=candidate`), adds `req-schema.json`, gates 1/3/6, advisory dependency audit, D3 documents (`AGENTS.md`, `Prompt.md`, permission model), D4 records.
- Architecture: no product code; module layout untouched; constraints recorded for future slices (SC-1..SC-5).
- Code & tests: two CI validator scripts; ruff-clean; no runtime impact.
- Ops/security: AI-use log intentionally absent at that point (team had not formally kicked off); rules files left empty for human authorship.
- Verdict: CHANGES REQUIRED at the time (pending human confirmation of the rules-file plan and the pre-draft registry values); merged after those confirmations.

## MEMO-0002 — PR #7 "docs(req): governance requirements (7 types complete) + gate adaptation"

- Spec: `REQ-TA-GOV-001..005` added as candidates; all seven D1 types represented; safety-critical path list grounded; `pip-audit` kept advisory; gate-4 trigger paths recorded.
- Architecture: docs/config only; mechanisms recorded are the ones already present in the baseline.
- Code & tests: schema gate re-validated against the grown registry (28 entries).
- Ops/security: no secrets, no new dependencies.
- Verdict: APPROVE (merged).

## MEMO-0003 — PR #61 "batch: FR-002 + FR-004 + FR-007 + FR-008 + QR-001 + QR-004 + QR-005 (2026-11-21)"

- Spec: batch merge to `main` of the requirement work integrated up to 2026-11-21.
- Architecture: ADR-003/004/005/007 work included; no architecture changes beyond those ADRs.
- Code & tests: full CI matrix green; offline suite 1887+ passing at that point.
- Ops/security: batch PR; trace and transcripts included in the same window.
- Verdict: APPROVE (merged).

## MEMO-0004 — PR #1 "Baseline/v0.7.1"

- Author/date: a5ynchr0ny, 2026-11-09. Diff: +17122/−5744 over 205 files.
- Spec: none (upstream baseline import).
- Architecture: baseline v0.7.1 snapshot.
- Code & tests: upstream suite imported; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0005 — PR #2 "chore(structure): adopt src/ layout and split offline/live tests"

- Author/date: a5ynchr0ny, 2026-11-09. Diff: +31/−8 over 189 files.
- Spec: none (structure).
- Architecture: src/ layout; offline/live split.
- Code & tests: path fixes in tests; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0006 — PR #3 "ci: run CI on integration branch pushes"

- Author/date: a5ynchr0ny, 2026-11-10. Diff: +1/−1 over 1 files.
- Spec: none (CI).
- Architecture: CI trigger for integration pushes.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0007 — PR #4 "docs(req): add requirements registry template"

- Author/date: a5ynchr0ny, 2026-11-09. Diff: +57/−0 over 1 files.
- Spec: D1 format (registry template).
- Architecture: docs/req/req-registry-template.yaml.
- Code & tests: schema pattern later; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0008 — PR #5 "docs(req): add candidate requirements catalogue"

- Author/date: Kwok-Kwok248, 2026-11-12. Diff: +817/−0 over 1 files.
- Spec: D1 input (candidate catalogue).
- Architecture: docs/req/requirement-candidates.md.
- Code & tests: n/a (analysis document); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0009 — PR #8 "batch: governance foundation + requirements registry (integration → main)"

- Author/date: a5ynchr0ny, 2026-11-15. Diff: +2168/−0 over 20 files.
- Spec: batch merge to `main`; batch to main.
- Architecture: governance foundation.
- Code & tests: CI matrix green; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0010 — PR #10 "Claim REQ-TA-FR-001"

- Author/date: wuyu200501, 2026-11-13. Diff: +1/−1 over 1 files.
- Spec: claims/assigns requirement ownership; REQ-TA-FR-001 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0011 — PR #11 "Claim/req xiaokewei001"

- Author/date: xiaokewei001, 2026-11-13. Diff: +5/−5 over 1 files.
- Spec: claims/assigns requirement ownership; REQ-TA-FR-002, REQ-TA-QR-001 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0012 — PR #13 "docs(requirements): record ownership of REQ-TA-FR-004 and REQ-TA-QR-005"

- Author/date: Kevin999-sudo, 2026-11-13. Diff: +2/−2 over 1 files.
- Spec: REQ-TA-FR-004, REQ-TA-QR-005 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0013 — PR #15 "claim REQ-TA-FR-005 / QR-002 / INV-005"

- Author/date: a5ynchr0ny, 2026-11-13. Diff: +3/−3 over 1 files.
- Spec: claims/assigns requirement ownership; REQ-TA-FR-005, QR-002, INV-005 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0014 — PR #16 "docs(req): claim REQ-TA-FR-008, REQ-TA-QR-004"

- Author/date: Kwok-Kwok248, 2026-11-13. Diff: +2/−2 over 1 files.
- Spec: REQ-TA-FR-008, QR-004 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0015 — PR #17 "docs(req): claim FR-007 and PERF-001"

- Author/date: LuwisSeraphia, 2026-11-14. Diff: +2/−2 over 1 files.
- Spec: REQ-TA-FR-007, PERF-001 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0016 — PR #19 "Add assignee tags for FR-002 and QR-001"

- Author/date: xiaokewei001, 2026-11-14. Diff: +2/−2 over 1 files.
- Spec: assignee tags for FR-002/QR-001.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0017 — PR #20 "sync: backfill main into integration after batch PR #8"

- Author/date: a5ynchr0ny, 2026-11-15. Diff: +0/−0 over 0 files.
- Spec: branch synchronisation; no requirement change.
- Architecture: n/a.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0018 — PR #21 "docs: align team readiness with course deliverables"

- Author/date: a5ynchr0ny, 2026-11-15. Diff: +39/−34 over 6 files.
- Spec: docs readiness alignment.
- Architecture: n/a.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0019 — PR #24 "Claim REQ-TA-QR-003"

- Author/date: wuyu200501, 2026-11-16. Diff: +2/−2 over 1 files.
- Spec: claims/assigns requirement ownership; REQ-TA-QR-003 claimed.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0020 — PR #27 "feat(FR-005): material claim traceability"

- Author/date: a5ynchr0ny, 2026-11-16. Diff: +1402/−20 over 19 files.
- Spec: REQ-TA-FR-005, QR-002, INV-005.
- Architecture: ADR-001 (material claims).
- Code & tests: test_claim_traceability, test_material_claims, test_traceability_invariant, test_report_disclaimer; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0021 — PR #29 "feat(FR-005): PM confidence field + QR-002 unconditional traceability"

- Author/date: a5ynchr0ny, 2026-11-17. Diff: +720/−62 over 17 files.
- Spec: FR-005 confidence; QR-002 unconditional; INV-005 fail-closed.
- Architecture: ADR-001 §4/§5.
- Code & tests: test_claim_acceptance (13 fn / 18 cases), updated audit tests; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0022 — PR #30 "REQ-TA-QR-003: Enforce component dependency boundaries"

- Author/date: wuyu200501, 2026-11-17. Diff: +1104/−2 over 5 files.
- Spec: REQ-TA-QR-003.
- Architecture: layering rule.
- Code & tests: test_layering.py (20+ cases); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0023 — PR #31 "REQ-TA-FR-001: Add quick, standard, and deep analysis profiles"

- Author/date: wuyu200501, 2026-11-17. Diff: +4617/−60 over 19 files.
- Spec: REQ-TA-FR-001.
- Architecture: ADR-002 (profiles).
- Code & tests: test_profiles*, test_cli_profile*, 71 profile tests; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0024 — PR #33 "batch: FR-001 profiles + FR-005 claim traceability + QR-003 boundaries"

- Author/date: a5ynchr0ny, 2026-11-17. Diff: +8314/−140 over 47 files.
- Spec: batch merge to `main`; batch to main (FR-001, FR-005, QR-003).
- Architecture: ADR-001, ADR-002.
- Code & tests: CI matrix green; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0025 — PR #34 "FR-007 / PERF-001 feat(eval): add configuration comparison and performance metrics"

- Author/date: LuwisSeraphia, 2026-11-17. Diff: +1046/−0 over 9 files.
- Spec: REQ-TA-FR-007, PERF-001.
- Architecture: ADR-007 (paired evaluation).
- Code & tests: test_evaluation*, docs/evaluation.md; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0026 — PR #35 "fix(FR-001): validate tool limits and resume legacy checkpoints"

- Author/date: wuyu200501, 2026-11-17. Diff: +489/−19 over 6 files.
- Spec: FR-001 follow-up fix.
- Architecture: ADR-002 (legacy checkpoint compatibility).
- Code & tests: test_checkpoint_lifecycle, test_profiles_graph; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0027 — PR #36 "sync: backfill main into integration"

- Author/date: a5ynchr0ny, 2026-11-17. Diff: +0/−0 over 0 files.
- Spec: branch synchronisation; no requirement change.
- Architecture: n/a.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0028 — PR #38 "Implement REQ-TA-QR-004 structured run metadata"

- Author/date: Kwok-Kwok248, 2026-11-17. Diff: +793/−31 over 7 files.
- Spec: REQ-TA-QR-004.
- Architecture: run_record schema v1.
- Code & tests: test_run_record.py; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0029 — PR #48 "feat(FR-002): per-run token budget with optional-call enforcement"

- Author/date: xiaokewei001, 2026-11-18. Diff: +2792/−88 over 36 files.
- Spec: REQ-TA-FR-002.
- Architecture: ADR-004 (token budget).
- Code & tests: test_token_budget, test_budget_* (361 budget tests); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0030 — PR #49 "Implement REQ-TA-FR-008 settings replay with FR-002 compatibility"

- Author/date: Kwok-Kwok248, 2026-11-19. Diff: +1106/−31 over 8 files.
- Spec: REQ-TA-FR-008.
- Architecture: ADR-004 amendment (budget not replayable).
- Code & tests: test_settings_replay, test_fr008_fr002_reconcile; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0031 — PR #51 "Unfreeze and assign REQ-TA-SEC-001"

- Author/date: Kwok-Kwok248, 2026-11-19. Diff: +3/−3 over 1 files.
- Spec: REQ-TA-SEC-001 unfreeze/assign.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0032 — PR #52 "feat(FR-004): validate final decision prices before adoption"

- Author/date: Kevin999-sudo, 2026-11-19. Diff: +1622/−22 over 22 files.
- Spec: REQ-TA-FR-004.
- Architecture: ADR-003 (decision validation).
- Code & tests: test_final_decision_validation; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0033 — PR #53 "test(QR-005): verify offline isolation and seeded test order"

- Author/date: Kevin999-sudo, 2026-11-19. Diff: +1020/−3 over 15 files.
- Spec: REQ-TA-QR-005.
- Architecture: offline isolation/seeded order.
- Code & tests: test_compare_orders, test_isolation_preflight, seeded-order plugin; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0034 — PR #54 "fix(FR-004): enforce review across fallback and decision displays"

- Author/date: Kevin999-sudo, 2026-11-19. Diff: +813/−30 over 12 files.
- Spec: FR-004 review across fallback/displays.
- Architecture: ADR-003.
- Code & tests: test_fr004_regression (493 lines); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0035 — PR #57 "fix(FR-004): validate and persist final decision prices"

- Author/date: Kevin999-sudo, 2026-11-19. Diff: +164/−10 over 8 files.
- Spec: FR-004 persist validated prices.
- Architecture: ADR-003.
- Code & tests: test_final_decision_validation (+71); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0036 — PR #60 "Feat/qr001 open code"

- Author/date: xiaokewei001, 2026-11-21. Diff: +1703/−44 over 26 files.
- Spec: REQ-TA-QR-001.
- Architecture: ADR-005 (controlled failures).
- Code & tests: test_qr001_* (6 files); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0037 — PR #63 "sync: backfill main into integration after batch #61"

- Author/date: a5ynchr0ny, 2026-11-21. Diff: +11/−0 over 1 files.
- Spec: branch synchronisation; no requirement change.
- Architecture: n/a.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0038 — PR #64 "Implement REQ-TA-SEC-001 secret redaction and leakage prevention"

- Author/date: Kwok-Kwok248, 2026-11-21. Diff: +1113/−5 over 13 files.
- Spec: REQ-TA-SEC-001.
- Architecture: ADR-006 (redaction + scan).
- Code & tests: test_sec001_redaction (37 tests); CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0039 — PR #65 "docs: consolidate WuYu transcripts and mark requirements implemented"

- Author/date: wuyu200501, 2026-11-21. Diff: +1951/−134 over 4 files.
- Spec: registry implemented flips + WuYu transcripts.
- Architecture: docs only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0040 — PR #66 "sync: backfill main into integration after SEC-001"

- Author/date: a5ynchr0ny, 2026-11-21. Diff: +1113/−5 over 13 files.
- Spec: branch synchronisation; no requirement change.
- Architecture: n/a.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0041 — PR #67 "Add 60884253 Alex engineering transcript"

- Author/date: Kwok-Kwok248, 2026-11-21. Diff: +449/−0 over 1 files.
- Spec: Alex transcript.
- Architecture: docs only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0042 — PR #69 "docs: archive FR-004 and QR-005 completion"

- Author/date: Kevin999-sudo, 2026-11-21. Diff: +3691/−2 over 2 files.
- Spec: FR-004/QR-005 archive.
- Architecture: docs only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0043 — PR #70 "docs(transcript): add FR-005 supervised transcript and align registry"

- Author/date: a5ynchr0ny, 2026-11-21. Diff: +14786/−9 over 3 files.
- Spec: FR-005 transcript + registry alignment.
- Architecture: docs only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0044 — PR #71 "fix(eval): complete comparison and record live evidence"

- Author/date: LuwisSeraphia, 2026-11-21. Diff: +17455/−50 over 64 files.
- Spec: FR-007/PERF-001 final evidence.
- Architecture: ADR-007; protocol qualification accepted in review.
- Code & tests: 18/18 live runs; comparison JSON/CSV; 5 new test files; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0045 — PR #72 "docs(security): record verified checksum false positives"

- Author/date: LuwisSeraphia, 2026-11-21. Diff: +2842/−0 over 1 files.
- Spec: SEC-001 baseline.
- Architecture: ADR-006.
- Code & tests: 354 SHA-256 entries verified entry-by-entry; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0046 — PR #73 "Mark Alex requirements implemented (QR-004, FR-008, SEC-001)"

- Author/date: Kwok-Kwok248, 2026-11-21. Diff: +3/−3 over 1 files.
- Spec: mark QR-004/FR-008/SEC-001 implemented.
- Architecture: registry only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0047 — PR #74 "requirements updated + transcripts"

- Author/date: xiaokewei001, 2026-11-21. Diff: +208/−2 over 2 files.
- Spec: registry updates + transcripts.
- Architecture: docs only.
- Code & tests: n/a; CI passed before merge.
- Ops/security: registry/log/transcript updates where applicable; no secrets introduced.
- Verdict: APPROVE (retrospective; merged).

## MEMO-0048 — Gate 4 "semantic evaluation (Portfolio Manager first version)" (pre-commit review)

- Spec: advances REQ-TA-GOV-001 / DEBT-003 (course gate 4) — a prompt/model change is evaluated against fixed inputs before merge. Split into Phase 1 (offline pre-check), Phase 2A (PM replay adapter), Phase 3A–C (formal baseline, gate decisions, CI real-evaluation path), and Phase 3D (candidate's actual model config). Thresholds remain **TBD** pending team review (`tools/ci/semantic_eval_thresholds.yaml`, the #81 path; a readable copy is in `docs/evidence/gate4/thresholds-draft.md`).
- Architecture: new `tools/sem_eval/*` package reuses the existing claim audit (`tradingagents.reporting.audit_material_claims`) and the production PM node; **no model whitelist and no hard-coded provider** — the real entry reuses the app's deep-tier resolution (`tier_provider` + `build_llm_kwargs` + `create_tier_client`) so the candidate's provider/model/temperature/reasoning settings reach the actual client. No `src/` changes; `ci.yml` untouched.
- CI: `gate4-semantic-eval.yml` is a **non-required** advisory check. The Draft-PR normal `pull_request` job injects **no** model credential (trigger + offline gate only; a triggered PR reports INFRASTRUCTURE_ERROR, never a fabricated PASS). The live replay for the current PR runs separately in a **trusted execution environment** that supplies only the candidate PM model's provider credential.
- Code & tests: gate decisions (PASS/REVIEW/FAIL/INFRASTRUCTURE_ERROR), REVIEW→observe, all-REVIEW→top-level PASS, empty/missing→infra; current-PR report records candidate SHA, case version, effective non-sensitive PM config (with `config_overridden` for manual runs), per-case results, verdict, failed rules. Multi-provider config switching covered by offline doubles (openai + anthropic). Offline tests: **112 Gate 4 tests pass**; full offline suite **2097 passed, 1 skipped**; `ruff check .` clean.
- Ops/security: docs-only PRs never read a credential (NOT_APPLICABLE before any config/key). The real call is confined to the trusted environment; only the selected provider's credential is read from the environment; unsupported provider / missing model / missing credential → INFRASTRUCTURE_ERROR with a fixed reason and no fallback. No key in the workflow, code, reports or logs.
- Evidence: baseline (3 cases × 3 runs) shows 3/9 runs carrying a hard defect the proposed rules would block (one unfounded 2026-06-19 date; two UNKNOWN_SOURCE). Baseline evidence, the DeepSeek `deepseek-flash` smoke, teammate records, the existing CI and app source are all preserved unchanged.
- Verdict: **APPROVE (pending team threshold review)** — suitable to open as a credential-free Draft PR; the gate stays advisory/non-blocking until thresholds are approved.
