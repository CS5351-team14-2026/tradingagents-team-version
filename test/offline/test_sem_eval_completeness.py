"""Gate 4 S1 — formal-CI report completeness (offline, no model, no network).

The Gate 4 issue under repair: the formal CI entry could return PASS for a
report that did not carry the full fixed evidence set. A report missing a case,
repeating one, running a case the wrong number of times, mis-numbering its runs,
or omitting the full-evidence case's ``expects_pass`` must be an
``INFRASTRUCTURE_ERROR`` (exit 2) that names exactly what is wrong — never a
partial ``PASS``.

Contract (Implements: REQ-TA-GOV-001 gate 4; Gate 4 completeness rule):

- exactly :data:`REQUIRED_CASE_IDS` (3 fixed cases), each **once**;
- each case exactly :data:`REQUIRED_REPETITIONS` (3) runs, numbered ``1..3``;
- the full-evidence case declares ``expects_pass: true``;
- a complete, clean report keeps its normal PASS/REVIEW/FAIL decision;
- a pure-docs change stays ``NOT_APPLICABLE`` (exit 0);
- ``decide_baseline`` keeps supporting single-case and archived historical
  reports (default ``require_complete=False``); only the formal CI entry
  (:func:`tools.sem_eval.ci_entry.evaluate_pr`) enforces completeness.

Uses offline model doubles via ``tools.sem_eval.replay`` plus static report
shapes; no real API call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval.ci_entry import evaluate_pr
from tools.sem_eval.gate import (
    REQUIRED_CASE_IDS,
    REQUIRED_REPETITIONS,
    check_completeness,
    decide_baseline,
)

PROMPT = ["src/tradingagents/agents/managers/portfolio_manager.py"]
DOCS = ["docs/evaluation.md", "README.md"]
FULL = "baseline_full_evidence_dated"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json"


# --- report builders -----------------------------------------------------

def _pass_run(rep):
    return {
        "repetition": rep,
        "id": "run",
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


def _review_run(rep):
    return {
        "repetition": rep,
        "id": "run",
        "audit_status": "DOWNGRADED",
        "observed_status": "DOWNGRADED",
        "observed_reasons": ["UNDATED_MARKET_DATA"],
        "claims_total": 1,
        "claims_attributed": 0,
        "unsupported_claim_ids": [],
        "claims": [
            {"kind": "supporting", "source": "UNKNOWN",
             "observation_date": None, "attributed": False,
             "reasons": ["UNDATED_MARKET_DATA"]},
        ],
        "observation_notes": [],
        "final_rating": "Hold",
        "confidence": "low",
        "decision_review_reasons": [],
        "matches_expectation": False,
        "evaluator_exception": False,
        "error": None,
    }


def _complete_report():
    """The full 3-case × 3-run evidence set : 1 PASS case + 2 REVIEW cases."""
    cases = [{"id": FULL, "expects_pass": True,
              "runs": [_pass_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}]
    for case_id in REQUIRED_CASE_IDS:
        if case_id == FULL:
            continue
        cases.append({"id": case_id,
                      "runs": [_review_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]})
    return {"status": "OBSERVE", "cases": cases}


# --- complete report keeps its normal decision ---------------------------

@pytest.mark.unit
def test_complete_clean_report_passes_through_formal_ci():
    result = evaluate_pr(PROMPT, report=_complete_report())
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["gate"]["completeness"]["ok"] is True


@pytest.mark.unit
def test_complete_report_with_failing_full_evidence_case_fails():
    report = _complete_report()
    failing = []
    for i in range(1, REQUIRED_REPETITIONS + 1):
        run = _pass_run(i)
        run["observation_notes"] = ["date basis unverified"]
        failing.append(run)
    report["cases"][0]["runs"] = failing
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert result["gate"]["completeness"]["ok"] is True


# --- REPRODUCED BUG: a thin-only report must not PASS --------------------

@pytest.mark.unit
def test_thin_only_report_that_used_to_pass_is_now_infrastructure_error():
    # The confirmed reproduction: a report containing ONLY
    # ``baseline_market_report_undated`` (a non-blocking REVIEW case). Before S1
    # this returned PASS/exit 0 because the missing cases were never noticed.
    report = {
        "status": "OBSERVE",
        "cases": [{"id": "baseline_market_report_undated",
                   "runs": [_review_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}],
    }
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert result["reason"] == "incomplete_report"
    # Names exactly what is missing.
    problems = result["completeness"]["problems"]
    assert f"missing_case:{FULL}" in problems
    assert "missing_case:baseline_partial_reports" in problems
    # And it is not, and never was, a PASS.
    assert result["status"] != "PASS"


# --- Each kind of incompleteness -----------------------------------------

@pytest.mark.unit
def test_missing_case_is_infrastructure_error():
    report = _complete_report()
    report["cases"] = [c for c in report["cases"] if c["id"] != "baseline_partial_reports"]
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "missing_case:baseline_partial_reports" in result["completeness"]["problems"]


@pytest.mark.unit
def test_duplicate_case_is_infrastructure_error():
    report = _complete_report()
    dup = {"id": "baseline_partial_reports",
           "runs": [_review_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}
    report["cases"].append(dup)
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "duplicate_case:baseline_partial_reports" in result["completeness"]["problems"]


@pytest.mark.unit
def test_insufficient_runs_is_infrastructure_error():
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == "baseline_partial_reports")
    case["runs"] = case["runs"][:2]  # only 2 of 3
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "run_count:baseline_partial_reports=2" in result["completeness"]["problems"]


@pytest.mark.unit
def test_duplicate_repetition_number_is_infrastructure_error():
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == "baseline_partial_reports")
    case["runs"][1]["repetition"] = 1  # [1, 1, 3]
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    problems = result["completeness"]["problems"]
    assert "duplicate_repetition:baseline_partial_reports" in problems
    assert "missing_repetition:baseline_partial_reports" in problems


@pytest.mark.unit
def test_wrong_repetition_set_is_infrastructure_error():
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == FULL)
    case["runs"][0]["repetition"] = 4  # [4, 2, 3] -> not 1..3, no duplicate
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "missing_repetition:baseline_full_evidence_dated" in result["completeness"]["problems"]


@pytest.mark.unit
def test_full_evidence_case_must_declare_expects_pass():
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == FULL)
    case["expects_pass"] = False
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "full_evidence_expects_pass" in result["completeness"]["problems"]


# --- Pure docs stays NOT_APPLICABLE --------------------------------------

@pytest.mark.unit
def test_pure_docs_change_is_not_applicable_even_without_complete_report():
    result = evaluate_pr(DOCS)  # no report at all
    assert result["status"] == "NOT_APPLICABLE"
    assert result["exit_code"] == 0
    assert result["matched_paths"] == []


# --- decide_baseline keeps single-case and historical support ------------

@pytest.mark.unit
def test_check_completeness_flags_complete_report_ok():
    assert check_completeness(_complete_report())["ok"] is True


@pytest.mark.unit
def test_decide_baseline_default_supports_single_case_report():
    # A single-case report is still decidable through the historical/unit path;
    # completeness is NOT enforced there (require_complete defaults to False).
    single = {"status": "OBSERVE", "cases": [
        {"id": FULL, "expects_pass": True,
         "runs": [_pass_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}]}
    decision = decide_baseline(single)
    assert decision["overall_decision"] == "PASS"
    # ...but formal CI rejects the same partial report.
    ci = evaluate_pr(PROMPT, report=single)
    assert ci["status"] == "INFRASTRUCTURE_ERROR"
    assert ci["exit_code"] == 2


@pytest.mark.unit
def test_decide_baseline_require_complete_rejects_partial_report():
    single = {"status": "OBSERVE", "cases": [
        {"id": FULL, "expects_pass": True,
         "runs": [_pass_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}]}
    decision = decide_baseline(single, require_complete=True)
    assert decision["overall_decision"] == "INFRASTRUCTURE_ERROR"
    assert decision["reasons"] == ["INCOMPLETE_REPORT"]
    assert decision["completeness"]["ok"] is False


@pytest.mark.unit
def test_historical_fixture_report_is_complete_and_keeps_normal_decision():
    # The fixed fixtures are the canonical complete set; replayed with a clean
    # model double the formal CI path keeps its normal decision (not an infra
    # error for incompleteness).
    from tools.sem_eval.replay import run_baseline
    from tradingagents.agents.schemas import (
        MaterialClaim,
        PortfolioDecision,
        PortfolioRating,
    )

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

    class _StructuredDouble:
        def __init__(self, decision):
            self._decision = decision

        def invoke(self, prompt):
            return self._decision

    class _LlmDouble:
        def __init__(self, decision):
            self._decision = decision

        def with_structured_output(self, schema, **kwargs):
            return _StructuredDouble(self._decision)

    dec = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="x",
        supporting_factors=[MaterialClaim(text="m", source_id="market_report",
                                          observation_date="2026-11-13")],
        opposing_factors=[MaterialClaim(text="v", source_id="investment_plan")],
    )
    replay = run_baseline(cases, llm_factory=lambda: _LlmDouble(dec),
                          repetitions=REQUIRED_REPETITIONS,
                          model_config={"provider": "deepseek",
                                        "model": "deepseek-flash"})
    result = evaluate_pr(PROMPT, report=replay)
    assert result["gate"]["completeness"]["ok"] is True
    assert result["status"] in {"PASS", "FAIL"}
    assert result["status"] != "INFRASTRUCTURE_ERROR"


# --- Boundary: expects_pass must be the boolean true ---------------------

@pytest.mark.unit
@pytest.mark.parametrize("bad_value", ["false", "False", "true", 1, 0, None, "yes"])
def test_expects_pass_must_be_boolean_true(bad_value):
    # Only the genuine boolean ``true`` is acceptance. ``"false"`` (a truthy
    # string) and ``1`` must NOT count as expects_pass.
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == FULL)
    case["expects_pass"] = bad_value
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "full_evidence_expects_pass" in result["completeness"]["problems"]


@pytest.mark.unit
def test_expects_pass_true_boolean_is_accepted():
    report = _complete_report()
    assert next(c for c in report["cases"] if c["id"] == FULL)["expects_pass"] is True
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "PASS"
    assert result["gate"]["completeness"]["ok"] is True


@pytest.mark.unit
def test_run_baseline_preserves_raw_expects_pass_value():
    # The report writer must not turn a malformed literal into bool True before
    # the gate sees it (the earlier ``bool(...)`` coercion hid "false"/1).
    from tools.sem_eval.replay import run_baseline
    from tradingagents.agents.schemas import (
        MaterialClaim,
        PortfolioDecision,
        PortfolioRating,
    )

    class _StructuredDouble:
        def __init__(self, decision):
            self._decision = decision

        def invoke(self, prompt):
            return self._decision

    class _LlmDouble:
        def __init__(self, decision):
            self._decision = decision

        def with_structured_output(self, schema, **kwargs):
            return _StructuredDouble(self._decision)

    dec = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="x",
        supporting_factors=[MaterialClaim(text="m", source_id="market_report",
                                          observation_date="2026-11-13")],
        opposing_factors=[MaterialClaim(text="v", source_id="investment_plan")],
    )
    case = {"id": FULL, "expects_pass": "false",
            "state": json.loads(FIXTURE.read_text(encoding="utf-8"))[0]["state"],
            "source_supported_dates": ["2026-11-13"]}
    replay = run_baseline([case], llm_factory=lambda: _LlmDouble(dec),
                          repetitions=REQUIRED_REPETITIONS,
                          model_config={"provider": "deepseek", "model": "deepseek-flash"})
    assert replay["cases"][0]["expects_pass"] == "false"  # preserved, not coerced
    # And the formal CI rejects it as incomplete.
    result = evaluate_pr(PROMPT, report=replay)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert "full_evidence_expects_pass" in result["completeness"]["problems"]


# --- Boundary: repetition numbers must be genuine ints 1..3 --------------

@pytest.mark.unit
@pytest.mark.parametrize("bad_rep", [True, False, 1.0, "1", [1], {"n": 1}])
def test_non_integer_repetition_is_infrastructure_error(bad_rep):
    # A bool, float, string, list or dict run number is invalid — never a crash,
    # and never a PASS. Returns INFRASTRUCTURE_ERROR/exit 2 with a reason.
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == "baseline_partial_reports")
    case["runs"][0]["repetition"] = bad_rep
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert result["exit_code"] == 2
    assert "invalid_repetition:baseline_partial_reports" in result["completeness"]["problems"]


@pytest.mark.unit
def test_bool_repetition_is_not_accepted_as_one():
    # ``True == 1`` in Python; completeness must reject it explicitly.
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == FULL)
    case["runs"][0]["repetition"] = True
    result = evaluate_pr(PROMPT, report=report)
    assert result["status"] == "INFRASTRUCTURE_ERROR"
    assert "invalid_repetition:baseline_full_evidence_dated" in result["completeness"]["problems"]


@pytest.mark.unit
def test_genuine_int_repetitions_1_to_3_are_accepted():
    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == FULL)
    assert [r["repetition"] for r in case["runs"]] == [1, 2, 3]
    assert evaluate_pr(PROMPT, report=report)["gate"]["completeness"]["ok"] is True


# --- Boundary: completeness problems land in report.json / summary.txt ---

@pytest.mark.unit
def test_completeness_problems_written_to_report_json_and_summary(tmp_path):
    from tools.sem_eval.reportgen import finalize_verdict, write_report

    # A report missing two cases -> INFRASTRUCTURE_ERROR; write the artefacts and
    # assert a reviewer sees the missing cases + their reasons on disk.
    only_thin = {
        "status": "OBSERVE",
        "cases": [{"id": "baseline_market_report_undated",
                   "runs": [_review_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}],
    }
    result = evaluate_pr(PROMPT, report=only_thin)
    assert result["reason"] == "incomplete_report"

    envelope = {
        "schema": 1,
        "candidate_sha": "incomplete123",
        "case_version": "x",
        "model_config": {"provider": "deepseek", "model": "deepseek-flash"},
        "repetitions": REQUIRED_REPETITIONS,
        "thresholds": "TBD",
        "replay": only_thin,
    }
    finalized = finalize_verdict(envelope, result)
    json_path, summary_path = write_report(finalized, tmp_path / "out")

    report_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert report_json["final_decision"] == "INFRASTRUCTURE_ERROR"
    assert report_json["reason"] == "incomplete_report"
    problems = report_json["completeness"]["problems"]
    assert f"missing_case:{FULL}" in problems
    assert "missing_case:baseline_partial_reports" in problems

    summary = summary_path.read_text(encoding="utf-8")
    assert "final_decision: INFRASTRUCTURE_ERROR" in summary
    assert "reason: incomplete_report" in summary
    assert "completeness: INCOMPLETE" in summary
    assert f"missing_case:{FULL}" in summary
    assert "missing_case:baseline_partial_reports" in summary


@pytest.mark.unit
def test_duplicate_repetition_written_to_summary(tmp_path):
    from tools.sem_eval.reportgen import finalize_verdict, write_report

    report = _complete_report()
    case = next(c for c in report["cases"] if c["id"] == "baseline_partial_reports")
    case["runs"][1]["repetition"] = 1  # duplicate
    result = evaluate_pr(PROMPT, report=report)
    envelope = {
        "schema": 1, "candidate_sha": "dup", "case_version": "x",
        "model_config": {"provider": "deepseek", "model": "deepseek-flash"},
        "repetitions": REQUIRED_REPETITIONS, "thresholds": "TBD", "replay": report,
    }
    finalized = finalize_verdict(envelope, result)
    _json_path, summary_path = write_report(finalized, tmp_path / "out")
    summary = summary_path.read_text(encoding="utf-8")
    assert "duplicate_repetition:baseline_partial_reports" in summary

