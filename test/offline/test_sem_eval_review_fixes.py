"""Gate 4 — review fixes: source-supported dates + acceptance gating (offline).

Addresses three review items with offline tests using a model double:

1. The fixed cases record the date their source reports actually support. A model
   date the source does not support (source 2026-11-13, model 2026-06-19) is
   UNFOUNDED_MARKET_DATE; a correct date passes; a missing date alone is REVIEW.
2. A full-evidence case must meet its own acceptance condition (every run PASS)
   before the whole group may be PASS. A reasoned REVIEW in a thin-evidence case
   is a recorded, non-blocking observation. The report keeps the PM decision and
   the audit downgrade reasons separate.
3. (README change is documentation; covered in docs, not here.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval.gate import decide_baseline
from tools.sem_eval.replay import run_baseline
from tradingagents.agents.schemas import MaterialClaim, PortfolioDecision, PortfolioRating

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json"


class _StructuredDouble:
    def __init__(self, decision):
        self._decision = decision

    def invoke(self, prompt):
        return self._decision


class _LlmDouble:
    def __init__(self, decision):
        self._decision = decision

    def with_structured_output(self, schema):  # noqa: ANN001 - mirror production
        return _StructuredDouble(self._decision)


def _decision_for(date: str | None, *, market_source: str = "market_report",
                  extra_unknown: bool = False) -> PortfolioDecision:
    """Hold with one market claim dated ``date`` (+ optional unknown source)."""
    supporting = [
        MaterialClaim(text="Market observation.", source_id=market_source,
                      observation_date=date)
    ]
    opposing = [MaterialClaim(text="Valuation risk.", source_id="investment_plan")]
    if extra_unknown:
        opposing.append(MaterialClaim(text="Unverified hearsay.",
                                      source_id="podcast_transcript"))
    return PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="Evidence.",
        supporting_factors=supporting, opposing_factors=opposing,
    )


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _run(cases, decision):
    return run_baseline(cases, llm_factory=lambda: _LlmDouble(decision),
                        repetitions=1, model_config={"provider": "deepseek",
                                                      "model": "deepseek-flash"})


# --- 1. Source-supported dates ------------------------------------------

@pytest.mark.unit
def test_unfounded_date_when_model_date_not_supported_by_source():
    # Full-evidence case's source supports 2026-11-13; the model supplies
    # 2026-06-19 -> UNFOUNDED_MARKET_DATE -> FAIL.
    full = next(c for c in _cases() if c["id"] == "baseline_full_evidence_dated")
    replay = _run([full], _decision_for("2026-06-19"))
    decision = decide_baseline(replay)
    run = decision["cases"][0]["runs"][0]
    assert run["decision"] == "FAIL"
    assert "UNFOUNDED_MARKET_DATE" in run["reasons"]


@pytest.mark.unit
def test_correct_supported_date_passes():
    full = next(c for c in _cases() if c["id"] == "baseline_full_evidence_dated")
    replay = _run([full], _decision_for("2026-11-13"))
    decision = decide_baseline(replay)
    run = decision["cases"][0]["runs"][0]
    assert run["decision"] == "PASS"
    assert "UNFOUNDED_MARKET_DATE" not in run["reasons"]


@pytest.mark.unit
def test_missing_date_alone_is_review_not_fail():
    # A market claim with no date: missing-date family, not unfounded -> REVIEW.
    full = next(c for c in _cases() if c["id"] == "baseline_full_evidence_dated")
    replay = _run([full], _decision_for(None))
    decision = decide_baseline(replay)
    run = decision["cases"][0]["runs"][0]
    assert run["decision"] == "REVIEW"
    assert run["blocks_merge"] is False
    assert "UNFOUNDED_MARKET_DATE" not in run["reasons"]


@pytest.mark.unit
def test_undated_source_rejects_any_supplied_date():
    und = next(c for c in _cases() if c["id"] == "baseline_market_report_undated")
    replay = _run([und], _decision_for("2026-06-19"))
    decision = decide_baseline(replay)
    run = decision["cases"][0]["runs"][0]
    assert run["decision"] == "FAIL"
    assert "UNFOUNDED_MARKET_DATE" in run["reasons"]


# --- 2. Acceptance gating + separated PM/audit reasons -------------------

@pytest.mark.unit
def test_full_evidence_pass_enables_group_pass():
    cases = _cases()
    # One decision that yields PASS on the full case (dated, supported) and a
    # non-blocking REVIEW on the thin cases is not possible with a single static
    # decision; test the full-evidence case alone drives its acceptance.
    full = next(c for c in cases if c["id"] == "baseline_full_evidence_dated")
    replay = _run([full], _decision_for("2026-11-13"))
    decision = decide_baseline(replay)
    assert decision["cases"][0]["expects_pass"] is True
    assert decision["cases"][0]["meets_acceptance"] is True
    assert decision["full_evidence_met"] is True
    assert decision["overall_decision"] == "PASS"


@pytest.mark.unit
def test_full_evidence_failure_blocks_group_pass():
    # Full-evidence case fails (wrong date) -> it does not meet acceptance; the
    # group cannot be PASS.
    full = next(c for c in _cases() if c["id"] == "baseline_full_evidence_dated")
    replay = _run([full], _decision_for("2026-06-19"))
    decision = decide_baseline(replay)
    assert decision["cases"][0]["meets_acceptance"] is False
    assert decision["full_evidence_met"] is False
    assert decision["overall_decision"] != "PASS"


@pytest.mark.unit
def test_thin_case_review_is_non_blocking_observation():
    # The undated case with only a missing date is REVIEW; not a hard defect.
    und = next(c for c in _cases() if c["id"] == "baseline_market_report_undated")
    replay = _run([und], _decision_for(None))
    decision = decide_baseline(replay)
    case = decision["cases"][0]
    assert case["expects_pass"] is False
    assert case["decision"] in ("PASS", "REVIEW")
    assert case["meets_acceptance"] is True
    # No hard-fail reason recorded.
    for run in case["runs"]:
        assert "UNFOUNDED_MARKET_DATE" not in run["reasons"]
        assert "UNRESOLVABLE_SOURCE" not in run["reasons"]


@pytest.mark.unit
def test_report_records_pm_decision_and_audit_reasons_separately():
    # An unknown source -> audit downgrade; the PM rating is still recorded.
    partial = next(c for c in _cases() if c["id"] == "baseline_partial_reports")
    replay = _run([partial], _decision_for(None, extra_unknown=True))
    decision = decide_baseline(replay)
    run = decision["cases"][0]["runs"][0]
    assert run["pm_decision"] == "Hold"            # PM decision
    assert "UNRESOLVABLE_SOURCE" in run["reasons"]  # gate/audit downgrade reason
    # The audit's own reason codes are preserved separately.
    assert "UNKNOWN_SOURCE" in run["audit_reasons"] or run["audit_status"] in (
        "DOWNGRADED", "NOT_ASSESSED")
