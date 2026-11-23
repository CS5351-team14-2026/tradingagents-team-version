"""Gate 4 S2 — rating provenance (offline, model double, no network).

The second PR #82 problem: after the Portfolio Manager model returns Buy, the
application can downgrade the run to ``REVIEW`` because the entry price / stop
loss is missing. Gate 4 previously mislabelled that as the model *choosing*
REVIEW (``EXPLICIT_REVIEW``). S2 keeps three things distinct in the replay JSON,
the finalized CI JSON and the readable summary:

- the model's **own** rating (or unknown when it cannot be safely recovered);
- the **application-validated** rating and its review reasons; and
- the **evidence-audit** status and reasons.

Invariants under test (Implements: REQ-TA-GOV-001 gate 4; REQ-TA-FR-004;
REQ-TA-INV-001):

- A ``REVIEW`` produced by the app's price policy from a real model call is
  ``APP_VALIDATION_REVIEW`` (``review_origin="app_validated"``), never
  ``EXPLICIT_REVIEW``.
- A missing/unparseable model rating is reported unknown
  (``review_origin="unknown"``), never assumed to be a model-explicit REVIEW.
- A normal, unchanged valid rating (e.g. Hold) keeps its validated rating and
  carries no review origin.
- Legacy ``pm_decision`` remains the validated rating; historical records with no
  provenance keep their old classification.
- No raw model prose reaches the report.

The production PM node is exercised through an offline structured model double.
Under an interpreter whose ``tradingagents`` import resolves to another checkout
(e.g. running this suite through WSL with a Windows venv), the real price
validation may differ; the provenance tests below are written to assert the
*recovery/classification* contract, which holds regardless of that layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.sem_eval.gate import decide_baseline, decide_run
from tools.sem_eval.replay import (
    REVIEW_ORIGIN_APP,
    REVIEW_ORIGIN_UNKNOWN,
    _recover_model_rating,
    _review_origin,
    run_baseline,
    run_case,
)
from tradingagents.agents.schemas import (
    MaterialClaim,
    PortfolioDecision,
    PortfolioRating,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "gate4" / "baseline_cases.json"
FULL = "baseline_full_evidence_dated"


# --- model double (structured, offline) ----------------------------------

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


def _state():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))[0]["state"]


def _buy_no_prices():
    """The production PM returns Buy with no entry/stop prices and no claims."""
    return PortfolioDecision(
        rating=PortfolioRating.BUY,
        confidence="high",
        executive_summary="Buy now.",
        investment_thesis="Momentum.",
        supporting_factors=[],
        opposing_factors=[],
    )


def _run_once(decision):
    case = {"id": FULL, "state": _state(), "source_supported_dates": ["2026-11-13"]}
    result = run_case(case, lambda: _LlmDouble(decision))
    # ``run_baseline`` stamps the repetition onto each run; mirror that so a
    # single-case result matches the shape ``decide_run`` sees in a real report.
    return {"repetition": 1, **result}


# --- recovery helpers: the trustworthy-provenance contract ---------------

@pytest.mark.unit
def test_recover_model_rating_from_controlled_render():
    produced = {
        "claim_fallback": None,
        "final_trade_decision": "**Rating**: Buy\n\n**Confidence**: high",
        "final_rating": "REVIEW",
        "decision_review_reasons": ["missing_entry_price", "missing_stop_loss"],
    }
    assert _recover_model_rating(produced) == "Buy"


@pytest.mark.unit
def test_recover_model_rating_ignores_free_text_prose():
    # The free-text fallback stores raw model prose; it must not be parsed.
    produced = {
        "claim_fallback": "free_text",
        "final_trade_decision": "I think it is a Buy but whatever; Rating: Buy",
        "final_rating": "REVIEW",
        "decision_review_reasons": ["missing_entry_price"],
    }
    assert _recover_model_rating(produced) is None


@pytest.mark.unit
def test_recover_model_rating_unknown_when_unparseable():
    produced = {"claim_fallback": None, "final_trade_decision": "no rating here"}
    assert _recover_model_rating(produced) is None


@pytest.mark.unit
def test_review_origin_classification():
    reasons = ["missing_entry_price", "missing_stop_loss"]
    # A known model rating downgraded to REVIEW is an app-validation review.
    assert _review_origin("Buy", "REVIEW", reasons) == REVIEW_ORIGIN_APP
    # Positive evidence the model chose REVIEW is a model-explicit review.
    assert _review_origin("REVIEW", "REVIEW", reasons) == "model_explicit"
    # No model rating but recorded validation reasons: the app's hand is shown.
    assert _review_origin(None, "REVIEW", reasons) == REVIEW_ORIGIN_APP
    # No model rating and no validation reasons: unknown.
    assert _review_origin(None, "REVIEW", []) == REVIEW_ORIGIN_UNKNOWN
    # A non-REVIEW run has no review origin.
    assert _review_origin("Hold", "Hold", []) is None


# --- Reproduction: Buy -> REVIEW without prices (production PM double) ---

@pytest.mark.unit
def test_buy_without_prices_is_application_review_not_explicit_review():
    run = _run_once(_buy_no_prices())
    # Audit of a claim-less decision is NOT_ASSESSED (no claims to score).
    assert run["audit_status"] == "NOT_ASSESSED"
    # The model's own call is recovered; the run is validated to REVIEW by the
    # app's price policy, and provenance labels it an app-validation review.
    assert run["model_rating"] == "Buy"
    assert run["applied_rating"] == "REVIEW"
    assert "missing_entry_price" in run["applied_review_reasons"]
    assert "missing_stop_loss" in run["applied_review_reasons"]
    assert run["review_origin"] == REVIEW_ORIGIN_APP
    # The gate must NOT label this EXPLICIT_REVIEW.
    finding = decide_run(run)
    assert finding["decision"] == "REVIEW"
    assert "EXPLICIT_REVIEW" not in finding["reasons"]
    assert "APP_VALIDATION_REVIEW" in finding["reasons"]


@pytest.mark.unit
def test_buy_without_prices_through_full_replay_report():
    replay = run_baseline([{"id": FULL, "state": _state(),
                            "expects_pass": True,
                            "source_supported_dates": ["2026-11-13"]}],
                          llm_factory=lambda: _LlmDouble(_buy_no_prices()),
                          repetitions=1,
                          model_config={"provider": "deepseek", "model": "deepseek-flash"})
    run = replay["cases"][0]["runs"][0]
    assert run["model_rating"] == "Buy"
    assert run["applied_rating"] == "REVIEW"
    assert run["review_origin"] == REVIEW_ORIGIN_APP
    decision = decide_baseline(replay)
    run_view = decision["cases"][0]["runs"][0]
    # Legacy pm_decision is the validated rating, and provenance is recorded too.
    assert run_view["pm_decision"] == "REVIEW"
    assert run_view["model_rating"] == "Buy"
    assert run_view["applied_rating"] == "REVIEW"
    assert run_view["review_origin"] == REVIEW_ORIGIN_APP


# --- Unknown / ambiguous model rating ------------------------------------

@pytest.mark.unit
def test_unknown_model_rating_with_validation_reasons_is_app_validation():
    # Simulate the produced record for an unrecoverable model intent (free-text
    # fallback), but with recorded validation reasons: the model origin is unknown
    # while the *recorded reasons* show the app's downgrade hand, so the origin is
    # application validation (never a bare EXPLICIT_REVIEW).
    produced = {
        "claim_fallback": "free_text",
        "final_trade_decision": "some prose with no clear call",
        "final_rating": "REVIEW",
        "decision_review_reasons": ["missing_entry_price", "missing_stop_loss"],
    }
    model_rating = _recover_model_rating(produced)
    origin = _review_origin(model_rating, "REVIEW", produced["decision_review_reasons"])
    assert model_rating is None
    assert origin == REVIEW_ORIGIN_APP

    run = {
        "repetition": 1, "audit_status": "NOT_ASSESSED", "claims_total": 0,
        "claims_attributed": 0, "final_rating": "REVIEW", "evaluator_exception": False,
        "claims": [], "observed_reasons": ["NO_CLAIM_METADATA"], "observation_notes": [],
        "model_rating": None, "applied_rating": "REVIEW",
        "applied_review_reasons": ["missing_entry_price", "missing_stop_loss"],
        "review_origin": REVIEW_ORIGIN_APP,
    }
    finding = decide_run(run)
    assert finding["decision"] == "REVIEW"
    assert finding["reasons"] == ["APP_VALIDATION_REVIEW"]
    assert "EXPLICIT_REVIEW" not in finding["reasons"]


@pytest.mark.unit
def test_historical_record_without_provenance_is_unknown_not_explicit_review():
    # The archived historical baseline has no provenance and no recorded
    # validation reasons: keep the REVIEW severity, label the model origin
    # unknown, and never EXPLICIT_REVIEW without positive evidence.
    historical = {
        "repetition": 1, "audit_status": "NOT_ASSESSED", "claims_total": 0,
        "claims_attributed": 0, "final_rating": "REVIEW", "evaluator_exception": False,
        "claims": [], "observed_reasons": [],
    }
    finding = decide_run(historical)
    assert finding["decision"] == "REVIEW"
    assert finding["reasons"] == ["UNKNOWN_MODEL_REVIEW"]


@pytest.mark.unit
def test_historical_review_with_validation_reasons_is_app_validation():
    # A historical record with no model_rating but recorded validation reasons is
    # classified as application validation (still REVIEW, never EXPLICIT_REVIEW).
    historical = {
        "repetition": 1, "audit_status": "NOT_ASSESSED", "claims_total": 0,
        "claims_attributed": 0, "final_rating": "REVIEW", "evaluator_exception": False,
        "claims": [], "observed_reasons": [],
        "decision_review_reasons": ["missing_entry_price", "missing_stop_loss"],
    }
    finding = decide_run(historical)
    assert finding["decision"] == "REVIEW"
    assert finding["reasons"] == ["APP_VALIDATION_REVIEW"]


# --- Unchanged valid rating (no review) ----------------------------------

@pytest.mark.unit
def test_valid_hold_keeps_rating_and_has_no_review_origin():
    hold = PortfolioDecision(
        rating=PortfolioRating.HOLD, confidence="medium",
        executive_summary="Hold.", investment_thesis="Balanced.",
        supporting_factors=[MaterialClaim(text="m", source_id="market_report",
                                          observation_date="2026-11-13")],
        opposing_factors=[MaterialClaim(text="v", source_id="investment_plan")],
    )
    run = _run_once(hold)
    assert run["model_rating"] == "Hold"
    assert run["applied_rating"] == "Hold"
    assert run["applied_review_reasons"] == []
    assert run["review_origin"] is None


# --- Reporting: JSON + summary carry the provenance ----------------------

@pytest.mark.unit
def test_provenance_in_finalized_json_and_summary(tmp_path):
    from tools.sem_eval.ci_entry import evaluate_pr
    from tools.sem_eval.gate import REQUIRED_CASE_IDS, REQUIRED_REPETITIONS
    from tools.sem_eval.reportgen import finalize_verdict, write_report

    def _pass_run(rep):
        return {
            "repetition": rep, "id": "run", "audit_status": "ACCEPTED",
            "observed_status": "ACCEPTED", "observed_reasons": [],
            "claims_total": 6, "claims_attributed": 6, "unsupported_claim_ids": [],
            "claims": [{"kind": "supporting", "source": "market_report",
                        "observation_date": "2026-11-13", "attributed": True,
                        "reasons": []}],
            "observation_notes": [], "final_rating": "Overweight",
            "confidence": "medium", "decision_review_reasons": [],
            "model_rating": "Overweight", "applied_rating": "Overweight",
            "applied_review_reasons": [], "review_origin": None,
            "matches_expectation": False,
            "evaluator_exception": False, "error": None,
        }

    def _thin_run(rep):
        return {
            "repetition": rep, "id": "run", "audit_status": "DOWNGRADED",
            "observed_status": "DOWNGRADED", "observed_reasons": ["UNDATED_MARKET_DATA"],
            "claims_total": 1, "claims_attributed": 0, "unsupported_claim_ids": [],
            "claims": [{"kind": "supporting", "source": "UNKNOWN",
                        "observation_date": None, "attributed": False,
                        "reasons": ["UNDATED_MARKET_DATA"]}],
            "observation_notes": [], "final_rating": "Hold", "confidence": "low",
            "decision_review_reasons": [], "model_rating": "Hold",
            "applied_rating": "Hold", "applied_review_reasons": [],
            "review_origin": None,
            "matches_expectation": False, "evaluator_exception": False, "error": None,
        }

    cases = [{"id": FULL, "expects_pass": True,
              "runs": [_pass_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]}]
    for case_id in REQUIRED_CASE_IDS:
        if case_id != FULL:
            cases.append({"id": case_id,
                          "runs": [_thin_run(i) for i in range(1, REQUIRED_REPETITIONS + 1)]})
    report = {"status": "OBSERVE", "cases": cases}

    result = evaluate_pr(["src/tradingagents/agents/managers/portfolio_manager.py"],
                        report=report)
    envelope = {
        "schema": 1, "candidate_sha": "prov123", "case_version": "x",
        "model_config": {"provider": "deepseek", "model": "deepseek-flash"},
        "repetitions": REQUIRED_REPETITIONS, "thresholds": "TBD", "replay": report,
    }
    finalized = finalize_verdict(envelope, result)
    json_path, summary_path = write_report(finalized, tmp_path / "out")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    run_view = data["cases"][0]["runs"][0]
    assert run_view["model_rating"] == "Overweight"
    assert run_view["applied_rating"] == "Overweight"
    assert "applied_review_reasons" in run_view
    assert "audit_status" in run_view
    assert "audit_reasons" in run_view

    summary = summary_path.read_text(encoding="utf-8")
    assert "model=Overweight" in summary
    assert "validated=Overweight" in summary
    assert "audit=ACCEPTED" in summary
