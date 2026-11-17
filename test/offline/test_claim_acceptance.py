"""ADR-001 fail-closed: a run whose material claims do not resolve is not accepted.

These tests pin the acceptance verdict that REQ-TA-QR-002 and REQ-TA-INV-005 ask
for: every formally defined material claim resolves to a report artifact and a
derivable producing agent, and an untraceable claim — or no claim metadata at
all — prevents acceptance. The verdict is a report property, so REQ-TA-INV-001
holds throughout: it never changes the rating, and REVIEW stays REVIEW.
"""

import json

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.memory import TradingMemoryLog
from tradingagents.reporting import (
    CLAIM_ACCEPTANCE_STATUSES,
    CLAIM_NOT_ACCEPTED_NOTICE,
    audit_material_claims,
    evaluate_claim_acceptance,
    write_report_tree,
)

TRADE_DATE = "2026-11-14"

# The REQ-TA-FR-006 run-status enum is a candidate requirement, not this slice's
# to introduce: no verdict may ever carry one of its values.
_FR_006_STATUSES = frozenset({
    "COMPLETED", "COMPLETED_WITH_WARNINGS", "INSUFFICIENT_DATA",
    "AGENT_DISAGREEMENT_REQUIRES_REVIEW",
})


def _traced_claims():
    return [
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "market_report", "observation_date": TRADE_DATE},
        {"kind": "opposing", "text": "Trader cautious.",
         "source_id": "trader_investment_plan"},
    ]


def _untraceable_claims():
    claims = _traced_claims()
    claims[0]["source_id"] = "podcast_transcript"
    return claims


def _state(**overrides):
    state = {
        "company_of_interest": "NVDA",
        "trade_date": TRADE_DATE,
        "market_report": "Market report.",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_debate_state": {"bull_history": "", "bear_history": "",
                                    "history": "", "current_response": ""},
        "trader_investment_plan": "Trader plan.",
        "investment_plan": "Plan.",
        "risk_debate_state": {"aggressive_history": "", "conservative_history": "",
                              "neutral_history": "", "history": ""},
        "final_trade_decision": "**Rating**: Hold",
        "final_rating": "Hold",
        "material_claims": _traced_claims(),
    }
    state.update(overrides)
    return state


def _graph(tmp_path, enforced=True):
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "results_dir": str(tmp_path), "llm_provider": "openai",
        "deep_think_llm": "d", "quick_think_llm": "q",
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1,
        "output_language": "English", "data_vendors": {}, "tool_vendors": {},
        "claim_enforcement": enforced,
    }
    graph.selected_analysts = ("market",)
    graph.memory_log = TradingMemoryLog({"memory_log_path": str(tmp_path / "m.md")})
    return graph


def _logged(tmp_path):
    path = next(tmp_path.rglob(f"full_states_log_{TRADE_DATE}.json"))
    return json.loads(path.read_text(encoding="utf-8"))


# --- The verdict -----------------------------------------------------------


@pytest.mark.unit
def test_an_accepted_audit_yields_an_accepted_run():
    """REQ-TA-QR-002: every material claim resolves, so the report is accepted."""
    verdict = evaluate_claim_acceptance(_state(), enforced=True)

    assert verdict["status"] == "ACCEPTED"
    assert verdict["audit_status"] == "ACCEPTED"
    assert verdict["enforced"] is True
    assert verdict["reasons"] == []
    assert verdict["notice"] is None


@pytest.mark.unit
def test_a_downgraded_audit_rejects_the_run_and_names_reasons(tmp_path):
    """REQ-TA-QR-002 / REQ-TA-INV-005: an untraceable claim is not accepted."""
    state = _state(material_claims=_untraceable_claims())

    verdict = evaluate_claim_acceptance(state, enforced=True)

    assert verdict["status"] == "REJECTED"
    assert verdict["audit_status"] == "DOWNGRADED"
    assert "UNKNOWN_SOURCE" in verdict["reasons"]
    assert verdict["notice"] == CLAIM_NOT_ACCEPTED_NOTICE


@pytest.mark.unit
@pytest.mark.parametrize("claims", [None, []], ids=["none", "empty-list"])
def test_a_run_with_no_claim_metadata_is_rejected_under_enforcement(claims):
    """REQ-TA-INV-005: a run with no claim metadata is not acceptance (ADR-001 §3)."""
    verdict = evaluate_claim_acceptance(_state(material_claims=claims), enforced=True)

    assert verdict["status"] == "REJECTED"
    assert verdict["audit_status"] == "NOT_ASSESSED"
    assert verdict["reasons"] == ["NO_CLAIM_METADATA"]


@pytest.mark.unit
def test_an_unknown_source_is_rejected_and_the_claim_stays_visible(tmp_path):
    """REQ-TA-INV-005: the claim is labelled unsupported, never silently dropped."""
    state = _state(material_claims=_untraceable_claims())

    report = write_report_tree(state, "NVDA", tmp_path).read_text(encoding="utf-8")

    assert "- Acceptance: REJECTED" in report
    assert "UNSUPPORTED" in report and "UNKNOWN_SOURCE" in report
    assert "Close was 181.2." in report


@pytest.mark.unit
def test_enforcement_disabled_never_claims_acceptance():
    """The unenforced path says so, so it can never read as ACCEPTED."""
    verdict = evaluate_claim_acceptance(_state(), enforced=False)

    assert verdict["status"] == "NOT_ENFORCED"
    assert verdict["status"] != "ACCEPTED"
    assert verdict["enforced"] is False
    assert "CLAIM_ENFORCEMENT_DISABLED" in verdict["reasons"]


# --- REQ-TA-INV-001: the verdict is not a rating ---------------------------


@pytest.mark.unit
@pytest.mark.parametrize("claims,enforced,expected", [
    (_traced_claims(), True, "ACCEPTED"),
    (_untraceable_claims(), True, "REJECTED"),
    (None, True, "REJECTED"),
    (_traced_claims(), False, "NOT_ENFORCED"),
], ids=["accepted", "downgraded", "not-assessed", "not-enforced"])
def test_the_verdict_never_changes_the_final_rating(tmp_path, claims, enforced, expected):
    state = _state(material_claims=claims, final_rating="Underweight",
                   final_trade_decision="**Rating**: Underweight")
    graph = _graph(tmp_path, enforced=enforced)

    graph.record_decision("NVDA", TRADE_DATE, state)

    assert state["claim_acceptance"]["status"] == expected
    assert state["final_rating"] == "Underweight"
    assert _logged(tmp_path)["final_rating"] == "Underweight"
    assert [entry["rating"] for entry in graph.memory_log.load_entries()] == ["Underweight"]


@pytest.mark.unit
@pytest.mark.parametrize("claims", [_traced_claims(), _untraceable_claims()])
def test_a_review_rating_stays_review_whatever_the_verdict(tmp_path, claims):
    """REQ-TA-INV-001 with REQ-TA-FR-004: the validation gate outranks acceptance."""
    state = _state(material_claims=claims, final_rating="REVIEW",
                   final_trade_decision="No labelled rating here.")
    graph = _graph(tmp_path)

    graph.record_decision("NVDA", TRADE_DATE, state)

    assert state["final_rating"] == "REVIEW"
    assert _logged(tmp_path)["final_rating"] == "REVIEW"


# --- Recording -------------------------------------------------------------


@pytest.mark.unit
def test_record_decision_stores_the_verdict_in_the_state_log(tmp_path):
    """REQ-TA-QR-002: the acceptance verdict is part of the run's record."""
    state = _state(material_claims=_untraceable_claims())

    _graph(tmp_path).record_decision("NVDA", TRADE_DATE, state)

    logged = _logged(tmp_path)["claim_acceptance"]
    assert logged["status"] == "REJECTED"
    assert logged["audit_status"] == "DOWNGRADED"
    assert logged["enforced"] is True
    assert logged["notice"] == CLAIM_NOT_ACCEPTED_NOTICE


# --- Both renderings -------------------------------------------------------


@pytest.mark.unit
def test_a_rejected_report_states_the_acceptance_and_the_notice(tmp_path):
    """REQ-TA-FR-005: the report does not present an untraceable call as accepted."""
    report = write_report_tree(_state(material_claims=_untraceable_claims()), "NVDA",
                               tmp_path).read_text(encoding="utf-8")

    assert "## Acceptance" in report
    assert "- Acceptance: REJECTED" in report
    assert CLAIM_NOT_ACCEPTED_NOTICE in report
    assert report.index("## Acceptance") < report.index("## I. Analyst Team Reports")


@pytest.mark.unit
def test_a_rejected_html_report_states_the_acceptance(tmp_path):
    """REQ-TA-FR-005: the HTML page says what the Markdown report says."""
    write_report_tree(_state(material_claims=_untraceable_claims()), "NVDA", tmp_path)
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")

    assert ">REJECTED<" in page
    assert CLAIM_NOT_ACCEPTED_NOTICE in page


@pytest.mark.unit
def test_an_accepted_report_carries_no_non_acceptance_notice(tmp_path):
    write_report_tree(_state(), "NVDA", tmp_path)
    report = (tmp_path / "complete_report.md").read_text(encoding="utf-8")
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")

    assert "## Acceptance" not in report
    assert "Acceptance:" not in report
    assert CLAIM_NOT_ACCEPTED_NOTICE not in report
    assert CLAIM_NOT_ACCEPTED_NOTICE not in page


@pytest.mark.unit
def test_a_report_without_a_decision_gets_no_acceptance_block(tmp_path):
    """Nothing to accept: a failed run is reported as such, not as a rejection."""
    state = _state(final_trade_decision=None, final_rating="REVIEW", material_claims=None)

    report = write_report_tree(state, "NVDA", tmp_path).read_text(encoding="utf-8")

    assert "## Acceptance" not in report


# --- Boundaries ------------------------------------------------------------


@pytest.mark.unit
def test_the_verdict_never_uses_a_run_status_or_an_audit_status():
    """The three vocabularies are disjoint: acceptance is its own thing."""
    assert set(CLAIM_ACCEPTANCE_STATUSES) == {"ACCEPTED", "REJECTED", "NOT_ENFORCED"}
    assert not CLAIM_ACCEPTANCE_STATUSES & _FR_006_STATUSES
    assert "ACCEPTED" in {audit_material_claims(_state())["status"]}
    assert audit_material_claims(_state())["status"] != "NOT_ENFORCED"
