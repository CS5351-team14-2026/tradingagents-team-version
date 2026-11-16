# Trace matrix — FR-005 / QR-002 / INV-005

Only the requirements this slice implements are listed. The authoritative
registry is `docs/req/requirements.yaml`; the claim contract is ADR-001.

| Requirement | Component | Test | Monitor |
|---|---|---|---|
| REQ-TA-FR-005 (evidence-linked recommendation, dated observations, unsupported labels, notice) | `agents/schemas.py` (`MaterialClaim`, `PortfolioDecision.supporting_factors` / `opposing_factors`, `render_pm_decision`); `agents/managers/portfolio_manager.py`; `reporting.py` (`render_claim_ledger`, `NOT_INVESTMENT_ADVICE`); `report_html.py` | `test/offline/test_material_claims.py`; `test/offline/test_claim_traceability.py`; `test/offline/test_report_disclaimer.py`; `test/offline/test_report_html_claims.py` | Report header `Traceability:` line; markdown `## Evidence Linkage` ledger; HTML `Evidence Linkage` section; disclaimer in both renderings |
| REQ-TA-QR-002 (material-claim attribution fraction; source and producing agent identifiable) | `reporting.py` (`source_vocabulary`, `audit_material_claims`, `render_claim_ledger`) | `test/offline/test_claim_traceability.py`; `test/offline/test_material_claims.py`; `test/offline/test_report_html_claims.py` | `claims_attributed` / `claims_total` in the audit and report header; sampled human claim audit (row-3 measurement still TBD) |
| REQ-TA-INV-005 (no untraceable material claim in an accepted report) | `reporting.py` (`audit_material_claims` status and reason codes) | `test/offline/test_traceability_invariant.py` | `DOWNGRADED` + reason codes; `UNSUPPORTED` labels in both renderings; `claim_audit` in `AgentState` (run-path wiring deferred) |

`ClaimAudit` status is a report-level traceability status; it does not affect
`final_rating` or the REVIEW rule (REQ-TA-INV-001 / REQ-TA-FR-004).
