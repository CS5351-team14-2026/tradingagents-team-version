"""A traced recommendation: every material claim resolves to a report artifact.

Covers the positive path for REQ-TA-FR-005 and the structural clause of
REQ-TA-QR-002: an analyst output and a dated observation are present, and the
attribution fraction is computed from the claims themselves.
"""

import pytest

from tradingagents.reporting import audit_material_claims, write_report_tree


def _state(**overrides):
    state = {
        "trade_date": "2026-11-14",
        "market_report": "# Market view\n\nClose 181.2 on 2026-11-14.",
        "sentiment_report": "Sentiment.",
        "news_report": "News.",
        "fundamentals_report": "Fundamentals.",
        "investment_debate_state": {"bull_history": "Bull.", "bear_history": "Bear."},
        "investment_plan": "Plan.",
        "trader_investment_plan": "Trade.",
        "risk_debate_state": {
            "aggressive_history": "Agg.",
            "conservative_history": "Con.",
            "neutral_history": "Neu.",
        },
        "final_trade_decision": "**Rating**: Overweight\n\nAdd on weakness.",
        "final_rating": "Overweight",
        "material_claims": [
            {"kind": "supporting", "text": "Close was 181.2.",
             "source_id": "market_report", "observation_date": "2026-11-14"},
            {"kind": "supporting", "text": "News flow improved.", "source_id": "news_report"},
            {"kind": "supporting", "text": "Fundamentals steady.",
             "source_id": "fundamentals_report"},
            {"kind": "opposing", "text": "Sentiment mixed.", "source_id": "sentiment_report"},
            {"kind": "opposing", "text": "Risk debate split.",
             "source_id": "risk_debate_state.neutral_history"},
            {"kind": "opposing", "text": "Trader cautious.",
             "source_id": "trader_investment_plan"},
        ],
    }
    state.update(overrides)
    return state


@pytest.mark.unit
def test_every_material_claim_has_a_resolvable_source_and_producing_agent():
    audit = audit_material_claims(_state())

    assert audit["status"] == "ACCEPTED"
    assert audit["reasons"] == []
    assert audit["claims_attributed"] == audit["claims_total"] == 6
    assert all(claim["producer"] for claim in audit["claims"])


@pytest.mark.unit
def test_market_data_claims_render_their_observation_date(tmp_path):
    report = write_report_tree(_state(), "NVDA", tmp_path).read_text(encoding="utf-8")

    assert "market_report" in report and "Market Analyst" in report
    assert "@ 2026-11-14" in report


@pytest.mark.unit
def test_the_report_names_each_claim_source_next_to_the_claim(tmp_path):
    report = write_report_tree(_state(), "NVDA", tmp_path).read_text(encoding="utf-8")

    for claim, source in zip(_state()["material_claims"],
                             ("market_report", "news_report", "fundamentals_report",
                              "sentiment_report", "risk_debate_state.neutral_history",
                              "trader_investment_plan")):
        line = next(line for line in report.splitlines() if claim["text"] in line)
        assert source in line


@pytest.mark.unit
def test_the_recommendation_cites_an_analyst_output_and_a_dated_observation():
    no_analyst = [
        {"kind": "supporting", "text": "Plan is sound.", "source_id": "investment_plan"},
        {"kind": "opposing", "text": "Trader cautious.",
         "source_id": "trader_investment_plan"},
    ]
    audit = audit_material_claims(_state(material_claims=no_analyst))

    assert audit["status"] == "DOWNGRADED"
    assert "NO_ANALYST_REFERENCE" in audit["reasons"]
    assert "NO_DATED_OBSERVATION" in audit["reasons"]


@pytest.mark.unit
def test_the_attribution_fraction_is_computed_and_reported(tmp_path):
    audit = audit_material_claims(_state())
    report = write_report_tree(_state(), "NVDA", tmp_path).read_text(encoding="utf-8")

    assert audit["claims_attributed"] / audit["claims_total"] == 1.0
    assert "6 of 6 material claims attributed" in report


@pytest.mark.unit
def test_the_header_records_the_traceability_status(tmp_path):
    header = write_report_tree(_state(), "NVDA", tmp_path).read_text(
        encoding="utf-8").split("## ")[0]

    assert "- Traceability: ACCEPTED (6/6 material claims attributed)" in header


@pytest.mark.unit
def test_a_downgraded_run_states_its_reason(tmp_path):
    claims = _state()["material_claims"]
    claims[0] = {**claims[0], "source_id": "podcast_transcript"}
    report = write_report_tree(_state(material_claims=claims), "NVDA", tmp_path).read_text(
        encoding="utf-8")

    assert "- Traceability: DOWNGRADED" in report
    assert "UNKNOWN_SOURCE" in report
