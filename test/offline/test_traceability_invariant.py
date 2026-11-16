"""REQ-TA-INV-005 negative tests: an untraceable material claim is not accepted.

The checker is pure and offline. Fail-closed is not wired into the run path in
this slice, so a run with no claim metadata reports NOT_ASSESSED rather than
ACCEPTED (ADR-001 §4).
"""

import pytest

from tradingagents.reporting import audit_material_claims, write_report_tree


def _claims():
    return [
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "market_report", "observation_date": "2026-11-14"},
        {"kind": "opposing", "text": "Trader cautious.",
         "source_id": "trader_investment_plan"},
    ]


def _state(**overrides):
    state = {
        "trade_date": "2026-11-14",
        "market_report": "Market report.",
        "trader_investment_plan": "Trader plan.",
        "final_trade_decision": "**Rating**: Overweight\n\nAdd on weakness.",
        "final_rating": "Overweight",
        "material_claims": _claims(),
    }
    state.update(overrides)
    return state


@pytest.mark.unit
def test_a_fully_traced_report_is_accepted():
    assert audit_material_claims(_state())["status"] == "ACCEPTED"


@pytest.mark.unit
def test_an_untraceable_material_claim_downgrades_the_result():
    claims = _claims()
    claims[0]["text"] = "   "
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "UNTRACEABLE_CLAIM" in audit["reasons"]
    assert audit["unsupported_claim_ids"] == ["s1"]


@pytest.mark.unit
def test_a_claim_citing_an_unknown_artifact_downgrades_the_result():
    claims = _claims()
    claims[0]["source_id"] = "podcast_transcript"
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert audit["unsupported_claim_ids"] == ["s1"]
    assert "UNKNOWN_SOURCE" in audit["reasons"]


@pytest.mark.unit
def test_a_claim_citing_an_empty_artifact_downgrades_the_result():
    claims = _claims()
    claims[0]["source_id"] = "news_report"
    claims[0]["observation_date"] = None
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "UNKNOWN_SOURCE" in audit["reasons"]


@pytest.mark.unit
def test_a_market_data_claim_without_an_observation_date_downgrades_the_result():
    claims = _claims()
    claims[0]["observation_date"] = None
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "UNDATED_MARKET_DATA" in audit["reasons"]


@pytest.mark.unit
def test_a_future_observation_date_downgrades_the_result():
    claims = _claims()
    claims[0]["observation_date"] = "2027-01-01"
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert "INVALID_OBSERVATION_DATE" in audit["reasons"]


@pytest.mark.unit
def test_a_decision_without_claim_metadata_is_not_accepted():
    audit = audit_material_claims(_state(material_claims=None))

    assert audit["status"] == "NOT_ASSESSED"
    assert audit["status"] != "ACCEPTED"
    assert audit["reasons"] == ["NO_CLAIM_METADATA"]


@pytest.mark.unit
def test_unsupported_claims_stay_visible_and_labelled_unsupported(tmp_path):
    claims = _claims()
    claims[0]["source_id"] = "podcast_transcript"
    report = write_report_tree(_state(material_claims=claims), "NVDA", tmp_path).read_text(
        encoding="utf-8")

    assert "Close was 181.2." in report
    assert "UNSUPPORTED" in report and "UNKNOWN_SOURCE" in report


# --- Boundary tests for the number of material claims ---------------------


@pytest.mark.unit
@pytest.mark.parametrize("claims", [None, []], ids=["none", "empty-list"])
def test_zero_claims_is_never_accepted(claims):
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "NOT_ASSESSED"
    assert audit["status"] != "ACCEPTED"
    assert audit["reasons"] == ["NO_CLAIM_METADATA"]
    assert audit["claims_total"] == 0
    assert audit["unsupported_claim_ids"] == []


@pytest.mark.unit
def test_one_traceable_market_claim_is_accepted():
    claims = [{"kind": "supporting", "text": "Close was 181.2.",
               "source_id": "market_report", "observation_date": "2026-11-14"}]
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "ACCEPTED"
    assert audit["reasons"] == []
    assert audit["claims_total"] == audit["claims_attributed"] == 1


@pytest.mark.unit
def test_one_untraceable_claim_is_downgraded():
    claims = [{"kind": "supporting", "text": "Close was 181.2.",
               "source_id": "podcast_transcript", "observation_date": "2026-11-14"}]
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert audit["reasons"] == ["UNKNOWN_SOURCE"]
    assert audit["unsupported_claim_ids"] == ["s1"]


@pytest.mark.unit
def test_one_undated_market_claim_is_downgraded():
    claims = [{"kind": "supporting", "text": "Close was 181.2.",
               "source_id": "market_report", "observation_date": None}]
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "DOWNGRADED"
    assert audit["reasons"] == ["UNDATED_MARKET_DATA"]
    assert audit["unsupported_claim_ids"] == ["s1"]


@pytest.mark.unit
def test_two_traceable_claims_one_each_side_is_accepted():
    claims = [
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "market_report", "observation_date": "2026-11-14"},
        {"kind": "opposing", "text": "Trader cautious.",
         "source_id": "trader_investment_plan"},
    ]
    audit = audit_material_claims(_state(material_claims=claims))

    assert audit["status"] == "ACCEPTED"
    assert audit["reasons"] == []
    assert audit["claims_total"] == audit["claims_attributed"] == 2


@pytest.mark.unit
def test_a_free_text_fallback_names_the_fallback_reason():
    audit = audit_material_claims(_state(material_claims=None, claim_fallback="free_text"))

    assert audit["status"] == "NOT_ASSESSED"
    assert audit["reasons"] == ["NO_CLAIM_METADATA", "PM_FREETEXT_FALLBACK"]


@pytest.mark.unit
def test_a_structured_run_with_no_claims_has_only_no_claim_metadata():
    audit = audit_material_claims(_state(material_claims=[], claim_fallback=None))

    assert audit["status"] == "NOT_ASSESSED"
    assert audit["reasons"] == ["NO_CLAIM_METADATA"]
