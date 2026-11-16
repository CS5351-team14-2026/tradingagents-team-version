"""The material-claim contract fixed by ADR-001 (REQ-TA-FR-005 / REQ-TA-QR-002).

A material claim is exactly an item in the final recommendation's structured
supporting/opposing factor lists. Its source is an artifact key from the report
sections, and the producing agent is derived there, never self-reported.
"""

import pytest

from tradingagents.reporting import audit_material_claims, render_claim_ledger


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
        "material_claims": _claims(),
    }
    state.update(overrides)
    return state


def _claims():
    return [
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "market_report", "observation_date": "2026-11-14"},
        {"kind": "supporting", "text": "News flow improved.", "source_id": "news_report"},
        {"kind": "supporting", "text": "Fundamentals steady.", "source_id": "fundamentals_report"},
        {"kind": "opposing", "text": "Sentiment mixed.", "source_id": "sentiment_report"},
        {"kind": "opposing", "text": "Risk debate split.",
         "source_id": "risk_debate_state.neutral_history"},
        {"kind": "opposing", "text": "Trader cautious.", "source_id": "trader_investment_plan"},
    ]


@pytest.mark.unit
def test_a_material_claim_is_a_structured_factor_item():
    state = _state(final_trade_decision=(
        "**Rating**: Overweight\n\nRevenue rose 40% and margins improved. Add on weakness."))
    audit = audit_material_claims(state)

    assert audit["claims_total"] == 6
    assert audit["status"] == "ACCEPTED"
    assert "Revenue rose 40%" not in [claim["text"] for claim in audit["claims"]]


@pytest.mark.unit
def test_a_claim_source_id_must_name_a_report_artifact():
    claims = _claims()
    claims[0]["source_id"] = "podcast_transcript"
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "UNKNOWN_SOURCE" in audit["reasons"]
    assert audit["unsupported_claim_ids"] == ["s1"]


@pytest.mark.unit
def test_the_producing_agent_is_resolved_from_the_artifact_not_self_reported():
    claims = _claims()
    claims[1] = {**claims[1], "agent": "Bull Researcher"}
    audit = audit_material_claims(_state(material_claims=claims))

    by_id = {claim["id"]: claim for claim in audit["claims"]}
    assert by_id["s2"]["producer"] == "News Analyst"
    assert by_id["s2"]["attributed"] is True
    assert "Bull Researcher" not in render_claim_ledger(_state(material_claims=claims))


@pytest.mark.unit
def test_a_market_data_claim_requires_an_observation_date():
    claims = _claims()
    claims[0]["observation_date"] = None
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "UNDATED_MARKET_DATA" in audit["reasons"]
    assert audit["unsupported_claim_ids"] == ["s1"]


@pytest.mark.unit
def test_claim_ids_are_unique_and_stable_across_a_render():
    state = _state()
    first = audit_material_claims(state)
    second = audit_material_claims(state)

    ids = [claim["id"] for claim in first["claims"]]
    assert ids == ["s1", "s2", "s3", "o1", "o2", "o3"]
    assert ids == [claim["id"] for claim in second["claims"]]


@pytest.mark.unit
def test_more_than_three_claims_per_side_is_downgraded():
    claims = _claims() + [{"kind": "supporting", "text": "Fourth reason.",
                           "source_id": "investment_plan"}]
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "CLAIM_LIMIT_EXCEEDED" in audit["reasons"]
