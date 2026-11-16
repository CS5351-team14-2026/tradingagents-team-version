"""claim_audit is recorded with the run; claim_enforcement stays inert (ADR-001).

record_decision computes the pure audit before writing the state log, so every
run's log carries its ACCEPTED / DOWNGRADED / NOT_ASSESSED status. The reserved
claim_enforcement flag is configurable but no behaviour branches on it.
"""

import json

import pytest

from tradingagents.default_config import DEFAULT_CONFIG, build_default_config
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.memory import TradingMemoryLog

TRADE_DATE = "2026-11-14"


def _graph(tmp_path):
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "results_dir": str(tmp_path), "llm_provider": "openai",
        "deep_think_llm": "d", "quick_think_llm": "q",
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1,
        "output_language": "English", "data_vendors": {}, "tool_vendors": {},
        "claim_enforcement": False,
    }
    graph.selected_analysts = ("market",)
    graph.memory_log = TradingMemoryLog({"memory_log_path": str(tmp_path / "m.md")})
    return graph


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
    }
    state.update(overrides)
    return state


def _logged(tmp_path):
    path = next(tmp_path.rglob(f"full_states_log_{TRADE_DATE}.json"))
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_record_decision_writes_an_accepted_claim_audit(tmp_path):
    state = _state(material_claims=[
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "market_report", "observation_date": TRADE_DATE},
    ])
    _graph(tmp_path).record_decision("NVDA", TRADE_DATE, state)

    logged = _logged(tmp_path)["claim_audit"]
    assert logged["status"] == "ACCEPTED"
    assert logged["reasons"] == []
    assert logged["claims_total"] == logged["claims_attributed"] == 1
    assert _logged(tmp_path)["material_claims"] == state["material_claims"]


@pytest.mark.unit
def test_record_decision_writes_a_downgraded_claim_audit(tmp_path):
    state = _state(material_claims=[
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "podcast_transcript", "observation_date": TRADE_DATE},
    ])
    _graph(tmp_path).record_decision("NVDA", TRADE_DATE, state)

    logged = _logged(tmp_path)["claim_audit"]
    assert logged["status"] == "DOWNGRADED"
    assert "UNKNOWN_SOURCE" in logged["reasons"]
    assert logged["unsupported_claim_ids"] == ["s1"]


@pytest.mark.unit
def test_record_decision_writes_a_not_assessed_claim_audit(tmp_path):
    state = _state(material_claims=None)
    _graph(tmp_path).record_decision("NVDA", TRADE_DATE, state)

    logged = _logged(tmp_path)["claim_audit"]
    assert logged["status"] == "NOT_ASSESSED"
    assert logged["reasons"] == ["NO_CLAIM_METADATA"]
    assert logged["claims_total"] == 0


@pytest.mark.unit
def test_claim_enforcement_defaults_false_and_is_env_configurable(monkeypatch):
    assert DEFAULT_CONFIG["claim_enforcement"] is False

    monkeypatch.delenv("TRADINGAGENTS_CLAIM_ENFORCEMENT", raising=False)
    assert build_default_config()["claim_enforcement"] is False

    monkeypatch.setenv("TRADINGAGENTS_CLAIM_ENFORCEMENT", "true")
    assert build_default_config()["claim_enforcement"] is True


@pytest.mark.unit
def test_a_downgraded_audit_does_not_change_the_rating_or_memory_log(tmp_path):
    """claim_enforcement is False, so the audit is recorded without fail-closed."""
    state = _state(material_claims=[
        {"kind": "supporting", "text": "Close was 181.2.",
         "source_id": "podcast_transcript", "observation_date": TRADE_DATE},
    ])
    graph = _graph(tmp_path)
    graph.record_decision("NVDA", TRADE_DATE, state)

    assert graph.config["claim_enforcement"] is False
    assert state["final_rating"] == "Hold"
    assert _logged(tmp_path)["final_rating"] == "Hold"
    entries = graph.memory_log.load_entries()
    assert [(entry["ticker"], entry["rating"]) for entry in entries] == [("NVDA", "Hold")]
