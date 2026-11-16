"""A profile run records requested, overrides and resolved settings (REQ-TA-FR-001).

The report metadata must show what was asked for, which fields an explicit input
overrode, and the four settings actually used — in the Markdown report, the HTML
report and the state log alike. These tests run the graph offline with a scripted
model: deep, with the debate budget explicitly set to 1, so the risk budget stays
3 and the tool cap stays 20.
"""

from __future__ import annotations

import copy
import json

import pandas as pd
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from tradingagents.agents import context, schemas
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"
TEXT = "Report.\n\n**Rating**: Overweight\n\nFINAL TRANSACTION PROPOSAL: **BUY**"

STRUCTURED = {
    schemas.ResearchPlan: schemas.ResearchPlan(
        recommendation=schemas.PortfolioRating.OVERWEIGHT, rationale="r", strategic_actions="a"),
    schemas.TraderProposal: schemas.TraderProposal(action=schemas.TraderAction.BUY, reasoning="r"),
    schemas.PortfolioDecision: schemas.PortfolioDecision(
        rating=schemas.PortfolioRating.OVERWEIGHT, executive_summary="s",
        investment_thesis="Street consensus rating: Buy (28 of 35 analysts)."),
    schemas.SentimentReport: schemas.SentimentReport(
        overall_band=schemas.SentimentBand.NEUTRAL, overall_score=5.0, confidence="low", narrative="n"),
}

ARGS = {"symbol": "NVDA", "ticker": "NVDA", "curr_date": TRADE_DATE, "start_date": "2026-01-02",
        "end_date": TRADE_DATE, "indicator": "rsi", "topic": "Fed rate cut", "freq": "quarterly"}


class ScriptedModel(BaseChatModel):
    """Calls each bound tool once, then answers with TEXT (like the e2e test)."""

    structured: bool = False
    tools: tuple = ()
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools": tuple(tools)})

    def with_structured_output(self, schema, **kwargs):
        if not self.structured:
            raise NotImplementedError
        return RunnableLambda(lambda _: self.calls.append(1) or STRUCTURED[schema])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(1)
        if self.tools and not isinstance(messages[-1], ToolMessage):
            calls = [{"name": t.name, "id": f"call_{i}",
                      "args": {k: v for k, v in ARGS.items()
                               if k in t.tool_call_schema.model_json_schema()["properties"]}}
                     for i, t in enumerate(self.tools)]
            message = AIMessage(content="", tool_calls=calls)
        else:
            message = AIMessage(content=TEXT)
        return ChatResult(generations=[ChatGeneration(message=message)])


class _Client:
    def __init__(self, model):
        self.model = model

    def get_llm(self):
        return self.model


@pytest.fixture
def offline(monkeypatch):
    for method, vendors in router.VENDOR_METHODS.items():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, _m=method, **k: f"{_m} data")
    prices = pd.DataFrame({
        "Date": pd.bdate_range(end=TRADE_DATE, periods=60),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000_000,
    })
    monkeypatch.setattr(snapshot, "load_ohlcv", lambda *a, **k: prices.copy())
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "no posts")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "no posts")
    monkeypatch.setattr(yahoo_market.yf, "Ticker", lambda s: type("T", (), {"info": {"longName": "NVIDIA"}})())
    context._identity.cache_clear()


def _deep_override_run(tmp_path, monkeypatch):
    """Run deep with an explicit debate budget of 1; return the graph and its state-log path."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    model = ScriptedModel(structured=True)
    monkeypatch.setattr(trading_graph, "create_tier_client", lambda config, tier, **k: _Client(model))
    graph = trading_graph.TradingAgentsGraph(
        config=cfg, profile="deep", explicit_overrides={"max_debate_rounds": 1})
    graph.propagate("NVDA", TRADE_DATE)
    log = next((tmp_path / "results" / "NVDA" / "TradingAgentsStrategy_logs").glob("full_states_log_*.json"))
    return graph, log


@pytest.mark.unit
def test_run_settings_record_requested_overrides_and_resolved(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: run_settings() carries requested deep, the debate override, and
    the resolved four settings (debate 1, risk 3, tools 20, four analysts)."""
    graph, _ = _deep_override_run(tmp_path, monkeypatch)

    settings = graph.run_settings()
    assert settings["profile_requested"] == "deep"
    assert settings["profile_overrides"] == {"max_debate_rounds": 1}
    assert settings["analysts"] == ["market", "social", "news", "fundamentals"]
    assert settings["max_debate_rounds"] == 1
    assert settings["max_risk_discuss_rounds"] == 3
    assert settings["max_tool_rounds"] == 20
    assert settings["profile_resolved"] == {
        "analysts": ["market", "social", "news", "fundamentals"],
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 3,
        "max_tool_rounds": 20,
    }


@pytest.mark.unit
def test_the_state_log_records_requested_overrides_and_resolved(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: the state log's run_settings block carries the same three parts,
    and profile_resolved holds the actual analysts and the three round caps."""
    _, log = _deep_override_run(tmp_path, monkeypatch)

    block = json.loads(log.read_text(encoding="utf-8"))["run_settings"]
    assert block["profile_requested"] == "deep"
    assert block["profile_overrides"] == {"max_debate_rounds": 1}
    assert (block["max_debate_rounds"], block["max_risk_discuss_rounds"], block["max_tool_rounds"]) == (1, 3, 20)
    assert block["analysts"] == ["market", "social", "news", "fundamentals"]
    # ADR A.5: the resolved block names the actual analysts and the three round caps.
    assert block["profile_resolved"] == {
        "analysts": ["market", "social", "news", "fundamentals"],
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 3,
        "max_tool_rounds": 20,
    }


@pytest.mark.unit
def test_the_markdown_report_shows_requested_overrides_and_resolved(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: the Markdown header names the requested profile, the debate
    override and the resolved analysts/rounds/tool cap."""
    graph, _ = _deep_override_run(tmp_path, monkeypatch)
    state = {"trade_date": TRADE_DATE, "final_trade_decision": "**Rating**: Overweight",
             "market_report": "M"}
    path = graph.save_reports(state, "NVDA", save_path=tmp_path / "report", html=True)
    header = path.read_text(encoding="utf-8").split("## ")[0]

    assert "Analysis profile: deep (requested)" in header
    assert "Explicit overrides: max_debate_rounds=1" in header
    assert "Analysts: market, sentiment, news, fundamentals" in header
    assert "research debate rounds 1" in header
    assert "risk debate rounds 3" in header
    assert "tool rounds per analyst 20" in header


@pytest.mark.unit
def test_the_html_report_shows_requested_overrides_and_resolved(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: the HTML run details name the requested profile, the debate
    override and the resolved analysts/rounds/tool cap."""
    graph, _ = _deep_override_run(tmp_path, monkeypatch)
    state = {"trade_date": TRADE_DATE, "final_trade_decision": "**Rating**: Overweight",
             "market_report": "M"}
    graph.save_reports(state, "NVDA", save_path=tmp_path / "report", html=True)
    html = (tmp_path / "report" / "complete_report.html").read_text(encoding="utf-8")

    assert "deep (requested)" in html
    assert "max_debate_rounds=1" in html
    assert "market" in html and "sentiment" in html and "fundamentals" in html
    # The three round caps appear together in the debate-rounds detail.
    assert ">research<" in html and ">3<" in html and ">tools<" in html and ">20<" in html


@pytest.mark.unit
def test_a_bare_profile_run_records_no_overrides(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: a run that only selects a profile (the base analyst set is
    the profile's own) has an empty override list."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    graph = trading_graph.TradingAgentsGraph(
        config=cfg, profile="quick",
        # The CLI passes the resolved base (here the quick set) from the menu.
        base_analysts=("market", "news"))

    settings = graph.run_settings()
    assert settings["profile_requested"] == "quick"
    assert settings["profile_overrides"] == {}
    assert settings["profile_resolved"] == {
        "analysts": ["market", "news"],
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_rounds": 3,
    }


@pytest.mark.unit
def test_an_explicit_analyst_override_is_recorded_even_when_it_matches(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: an explicitly named analyst set is recorded as an override even
    when it equals the profile's own set."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    graph = trading_graph.TradingAgentsGraph(
        config=cfg, profile="quick",
        # Both a caller-selected set and an explicit override are given; the
        # explicit override wins and is the one recorded.
        selected_analysts=("market", "news", "fundamentals"),
        explicit_overrides={"analysts": ["market", "news"]})

    settings = graph.run_settings()
    assert settings["profile_overrides"] == {"analysts": ["market", "news"]}
    assert settings["profile_resolved"]["analysts"] == ["market", "news"]
    assert (settings["profile_resolved"]["max_debate_rounds"],
            settings["profile_resolved"]["max_risk_discuss_rounds"],
            settings["profile_resolved"]["max_tool_rounds"]) == (1, 1, 3)


@pytest.mark.unit
def test_a_crypto_filtered_set_shows_in_resolved_but_not_overrides(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: an asset-filtered base (crypto drops fundamentals) appears in
    profile_resolved without being recorded as a user override."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    graph = trading_graph.TradingAgentsGraph(
        config=cfg, profile="standard",
        base_analysts=("market", "social", "news"))  # crypto-filtered standard

    settings = graph.run_settings()
    assert settings["profile_overrides"] == {}
    assert settings["profile_resolved"]["analysts"] == ["market", "social", "news"]
    assert "fundamentals" not in settings["profile_resolved"]["analysts"]
