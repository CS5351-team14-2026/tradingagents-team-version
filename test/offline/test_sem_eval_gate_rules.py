"""Gate 4 Phase 3B — gate-decision logic (offline).

Uses the archived baseline evidence (read-only) and the existing report fields.
Verifies the four decision classes:

- PASS: full-evidence runs with every claim attributed and grounded dates.
- FAIL: an unfounded market date, or an unresolvable evidence source.
- REVIEW: thin evidence with no unfounded claim is an observation, not a block.
- INFRASTRUCTURE_ERROR: reported separately; never folded into REVIEW/FAIL.

Thresholds stay TBD; nothing blocks in this version.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.sem_eval.gate import DATE_BASIS_NOTE, UNKNOWN_SOURCE, decide_baseline, decide_run

BASELINE = (
    Path(__file__).resolve().parent.parent.parent
    / "docs" / "evidence" / "gate4" / "2026-11-22" / "baseline" / "baseline.json"
)


def _run(**overrides):
    run = {
        "repetition": 1,
        "id": "case",
        "audit_status": "ACCEPTED",
        "observed_status": "ACCEPTED",
        "observed_reasons": [],
        "claims_total": 6,
        "claims_attributed": 6,
        "unsupported_claim_ids": [],
        "claims": [
            {"kind": "supporting", "source": "market_report",
             "observation_date": "2026-11-13", "attributed": True, "reasons": []},
        ],
        "observation_notes": [],
        "final_rating": "Overweight",
        "confidence": "medium",
        "decision_review_reasons": [],
        "matches_expectation": False,
        "evaluator_exception": False,
        "error": None,
    }
    run.update(overrides)
    return run


# --- PASS ----------------------------------------------------------------

@pytest.mark.unit
def test_full_evidence_run_passes():
    finding = decide_run(_run())
    assert finding["decision"] == "PASS"
    assert finding["reasons"] == []
    assert finding["blocks_merge"] is False


# --- FAIL: unfounded market date -----------------------------------------

@pytest.mark.unit
def test_unfounded_market_date_fails():
    run = _run(observation_notes=[DATE_BASIS_NOTE])
    finding = decide_run(run)
    assert finding["decision"] == "FAIL"
    assert "UNFOUNDED_MARKET_DATE" in finding["reasons"]
    assert finding["blocks_merge"] is True


# --- FAIL: unresolvable evidence source ----------------------------------

@pytest.mark.unit
def test_unresolvable_source_fails():
    run = _run(claims=[
        {"kind": "supporting", "source": UNKNOWN_SOURCE,
         "observation_date": None, "attributed": False, "reasons": ["UNKNOWN_SOURCE"]},
    ], claims_total=1, claims_attributed=0, audit_status="DOWNGRADED")
    finding = decide_run(run)
    assert finding["decision"] == "FAIL"
    assert "UNRESOLVABLE_SOURCE" in finding["reasons"]
    assert finding["blocks_merge"] is True


# --- REVIEW: thin evidence, no hard defect -------------------------------

@pytest.mark.unit
def test_thin_evidence_without_defect_is_review_not_block():
    # DOWNGRADED, some claims unattributed by counts, but no UNKNOWN source and
    # no unfounded date note -> observe-only REVIEW.
    run = _run(
        audit_status="DOWNGRADED",
        claims_total=6,
        claims_attributed=4,
        claims=[
            {"kind": "supporting", "source": "market_report",
             "observation_date": "2026-11-13", "attributed": True, "reasons": []},
            {"kind": "opposing", "source": "trader_investment_plan",
             "observation_date": None, "attributed": True, "reasons": []},
        ],
        observation_notes=[],
    )
    finding = decide_run(run)
    assert finding["decision"] == "REVIEW"
    assert finding["reasons"] == ["THIN_EVIDENCE"]
    assert finding["blocks_merge"] is False


# --- INFRASTRUCTURE_ERROR separate ---------------------------------------

@pytest.mark.unit
def test_infrastructure_error_is_separate():
    run = _run(evaluator_exception=True, error="replay_error:RuntimeError",
               audit_status=None, claims=[], claims_total=None, claims_attributed=None)
    finding = decide_run(run)
    assert finding["decision"] == "INFRASTRUCTURE_ERROR"
    assert finding["blocks_merge"] is True


@pytest.mark.unit
def test_infrastructure_error_takes_precedence_over_other_signals():
    # Even if it also looks thin, an evaluator exception is infrastructure.
    run = _run(evaluator_exception=True, error="audit_error:RuntimeError",
               claims_total=6, claims_attributed=0)
    assert decide_run(run)["decision"] == "INFRASTRUCTURE_ERROR"


# --- Archived baseline: historical samples the new rules would catch -----

@pytest.mark.unit
def test_archived_baseline_decisions_match_expected_history():
    report = json.loads(BASELINE.read_text(encoding="utf-8"))
    original = copy.deepcopy(report)  # prove the input is not mutated
    decision = decide_baseline(report)

    assert report == original  # baseline evidence unchanged

    by_case = {c["id"]: c for c in decision["cases"]}

    # Full-evidence: all three PASS.
    full = by_case["baseline_full_evidence_dated"]
    assert [r["decision"] for r in full["runs"]] == ["PASS", "PASS", "PASS"]

    # Market-undated: runs 1 and 3 only miss a date on a market claim
    # (UNDATED_MARKET_DATA) with no supplied date -> REVIEW observation, NOT a
    # failure. Run 2 supplied 2026-06-19 with no source basis -> FAIL.
    und = by_case["baseline_market_report_undated"]
    und_run1 = next(r for r in und["runs"] if r["repetition"] == 1)
    und_run2 = next(r for r in und["runs"] if r["repetition"] == 2)
    und_run3 = next(r for r in und["runs"] if r["repetition"] == 3)
    assert und_run1["decision"] == "REVIEW"
    assert und_run1["blocks_merge"] is False
    assert und_run3["decision"] == "REVIEW"
    assert und_run3["blocks_merge"] is False
    assert und_run2["decision"] == "FAIL"
    assert "UNFOUNDED_MARKET_DATE" in und_run2["reasons"]
    assert und["decision"] == "FAIL"  # one FAIL among the runs

    # Partial reports: runs 1 and 2 truly reported UNKNOWN_SOURCE -> FAIL;
    # run 3 clean PASS.
    partial = by_case["baseline_partial_reports"]
    assert [r["decision"] for r in partial["runs"]] == ["FAIL", "FAIL", "PASS"]
    assert partial["decision"] == "FAIL"

    assert decision["overall_decision"] == "FAIL"
    assert decision["thresholds"] == "TBD"


@pytest.mark.unit
def test_new_rules_would_block_these_historical_samples():
    report = json.loads(BASELINE.read_text(encoding="utf-8"))
    decision = decide_baseline(report)
    blocked: list[str] = []
    for case in decision["cases"]:
        for run in case["runs"]:
            if run["blocks_merge"]:
                blocked.append(f"{case['id']}#{run['repetition']}:{','.join(run['reasons'])}")
    # 3 of 9 historical runs carry a hard defect the new rules would block:
    # one unfounded market date and two genuine UNKNOWN_SOURCE runs.
    assert len(blocked) == 3
    assert "baseline_market_report_undated#2:UNFOUNDED_MARKET_DATE" in blocked
    assert "baseline_partial_reports#1:UNRESOLVABLE_SOURCE" in blocked
    assert "baseline_partial_reports#2:UNRESOLVABLE_SOURCE" in blocked


# --- Fix 1: empty/missing reports never default to PASS ------------------

@pytest.mark.unit
def test_case_with_no_runs_is_infrastructure_error():
    report = {"cases": [{"id": "empty_case", "runs": []}]}
    decision = decide_baseline(report)
    assert decision["overall_decision"] == "INFRASTRUCTURE_ERROR"
    assert decision["cases"][0]["decision"] == "INFRASTRUCTURE_ERROR"
    assert decision["cases"][0]["reasons"] == ["missing_runs"]


@pytest.mark.unit
def test_top_level_report_with_no_cases_is_infrastructure_error():
    assert decide_baseline({"cases": []})["overall_decision"] == "INFRASTRUCTURE_ERROR"
    assert decide_baseline({})["overall_decision"] == "INFRASTRUCTURE_ERROR"


@pytest.mark.unit
def test_top_level_infrastructure_error_report_is_infrastructure_error():
    report = {"status": "INFRASTRUCTURE_ERROR", "reason": "empty_case_set", "cases": []}
    decision = decide_baseline(report)
    assert decision["overall_decision"] == "INFRASTRUCTURE_ERROR"
    assert decision["blocks_merge"] is True


@pytest.mark.unit
def test_run_with_no_claims_is_infrastructure_error_not_pass():
    run = _run(claims=[], claims_total=0, claims_attributed=0)
    finding = decide_run(run)
    assert finding["decision"] == "INFRASTRUCTURE_ERROR"
    assert finding["reasons"] == ["EMPTY_REPORT"]


@pytest.mark.unit
def test_run_missing_repetition_is_infrastructure_error():
    run = _run()
    del run["repetition"]
    assert decide_run(run)["decision"] == "INFRASTRUCTURE_ERROR"


# --- Fix 2: UNKNOWN_SOURCE reason code, not the display marker -----------

@pytest.mark.unit
def test_display_marker_without_unknown_source_reason_is_not_fail():
    # A market claim shown as source "UNKNOWN" (display marker) but whose audit
    # reason is the missing-date family, not UNKNOWN_SOURCE -> not an
    # unresolvable-source failure.
    run = _run(
        audit_status="DOWNGRADED",
        observed_reasons=["UNDATED_MARKET_DATA", "NO_DATED_OBSERVATION"],
        claims=[
            {"kind": "supporting", "source": UNKNOWN_SOURCE,
             "observation_date": None, "attributed": False,
             "reasons": ["UNDATED_MARKET_DATA"]},
        ],
        claims_total=1,
        claims_attributed=0,
    )
    finding = decide_run(run)
    assert finding["decision"] == "REVIEW"
    assert "UNRESOLVABLE_SOURCE" not in finding["reasons"]
    assert finding["blocks_merge"] is False


@pytest.mark.unit
def test_unknown_source_reason_code_triggers_fail():
    run = _run(
        audit_status="DOWNGRADED",
        observed_reasons=["UNKNOWN_SOURCE"],
        claims=[
            {"kind": "supporting", "source": UNKNOWN_SOURCE,
             "observation_date": None, "attributed": False,
             "reasons": ["UNKNOWN_SOURCE"]},
        ],
        claims_total=1,
        claims_attributed=0,
    )
    finding = decide_run(run)
    assert finding["decision"] == "FAIL"
    assert "UNRESOLVABLE_SOURCE" in finding["reasons"]


@pytest.mark.unit
def test_unfounded_date_still_fails_even_if_audit_accepted():
    run = _run(observation_notes=[DATE_BASIS_NOTE])  # ACCEPTED but date unfounded
    finding = decide_run(run)
    assert finding["decision"] == "FAIL"
    assert "UNFOUNDED_MARKET_DATE" in finding["reasons"]


# --- Explicit REVIEW with zero claims is REVIEW, not infra ---------------

@pytest.mark.unit
def test_complete_report_explicit_review_zero_claims_is_review():
    # A complete record where the model explicitly returned REVIEW and emitted
    # no claims is a valid outcome -> REVIEW (observe), not infrastructure error.
    run = _run(
        audit_status="NOT_ASSESSED",
        observed_status="NOT_ASSESSED",
        claims=[],
        claims_total=0,
        claims_attributed=0,
        final_rating="REVIEW",
        confidence=None,
        decision_review_reasons=["unresolved_rating"],
    )
    finding = decide_run(run)
    assert finding["decision"] == "REVIEW"
    assert finding["reasons"] == ["EXPLICIT_REVIEW"]
    assert finding["blocks_merge"] is False


@pytest.mark.unit
def test_zero_claims_without_explicit_review_is_infrastructure_error():
    # No claims and NOT an explicit REVIEW (still ACCEPTED/Overweight) -> the
    # record is not a complete, judgeable report.
    run = _run(claims=[], claims_total=0, claims_attributed=0, final_rating="Overweight")
    assert decide_run(run)["decision"] == "INFRASTRUCTURE_ERROR"


@pytest.mark.unit
@pytest.mark.parametrize(
    "missing",
    ["repetition", "audit_status", "claims_total", "claims_attributed",
     "final_rating", "evaluator_exception"],
)
def test_missing_required_field_is_infrastructure_error(missing):
    run = _run()
    del run[missing]
    assert decide_run(run)["decision"] == "INFRASTRUCTURE_ERROR"
