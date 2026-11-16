"""End-to-end CLI profile runs through the real graph (REQ-TA-FR-001).

These drive ``run_analysis`` with the actual ``TradingAgentsGraph`` (external
services replaced by offline doubles), so the analyst set, round budgets and the
terminal display are asserted on the graph the CLI really builds — not a fake.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

import cli.run as cli_run
from cli.models import AnalystType
from tradingagents.agents import context, schemas
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-10"
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


class _NullLive:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Buffer:
    def __init__(self):
        self.selected_analysts = []
        self.messages = []
        self.tool_calls = []
        self.agent_status = {}
        self.report_sections = {}
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        self.selected_analysts = list(selected_analysts)

    def add_message(self, kind, content):
        self.messages.append((0.0, kind, content))

    def add_tool_call(self, name, args):
        self.tool_calls.append((0.0, name, args))

    def update_report_section(self, *a):
        pass

    def update_agent_status(self, *a):
        pass


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
    monkeypatch.setattr(yahoo_market.yf, "Ticker", lambda s: type("T", (), {"info": {"longName": "X"}})())
    context._identity.cache_clear()
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: _Client(ScriptedModel(structured=True)))


def _drive(monkeypatch, tmp_path, ticker, asset_type, profile, analysts_selection,
           analysts_flag=None):
    """Run the real CLI path with the actual graph; return the buffer and the built graph."""
    built = {}
    real_graph = trading_graph.TradingAgentsGraph

    def _capture(*a, **k):
        g = real_graph(*a, **k)
        built["graph"] = g
        return g

    monkeypatch.setattr(cli_run, "TradingAgentsGraph", _capture)
    buffer = _Buffer()
    monkeypatch.setattr(cli_run, "message_buffer", buffer)
    monkeypatch.setattr(cli_run, "create_layout", lambda: None)
    monkeypatch.setattr(cli_run, "update_display", lambda *a, **k: None)
    monkeypatch.setattr(cli_run, "Live", _NullLive)
    # The interactive selection is supplied directly (the menu answered it).
    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags=None: {
        "ticker": ticker, "analysis_date": TRADE_DATE, "asset_type": asset_type,
        "analysts": [AnalystType(key) for key in analysts_selection],
        "research_depth": 1, "quick_think_llm": "q", "deep_think_llm": "d",
        "backend_url": None, "llm_provider": "openai", "google_thinking_level": None,
        "openai_reasoning_effort": None, "anthropic_effort": None, "output_language": "English",
    })
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    monkeypatch.setattr(cli_run, "_build_run_config",
                        lambda selections, checkpoint, profile=None: cfg)
    monkeypatch.setattr(cli_run.typer, "prompt", lambda *a, **k: "N")

    cli_run.run_analysis(
        flags={"ticker": ticker, "date": TRADE_DATE, "analysts": analysts_flag,
               "save": False, "show": False, "html": None},
        profile=profile,
    )
    return buffer, built["graph"]


@pytest.mark.unit
def test_omitted_profile_runs_exactly_the_menu_selection(monkeypatch, tmp_path, offline):
    """REQ-TA-FR-001: with no profile, a menu that picked only news runs only news —
    the execution plan, the progress buffer and the graph agree."""
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    buffer, graph = _drive(monkeypatch, tmp_path, "NVDA", "stock", profile=None,
                           analysts_selection=["news"])

    assert graph.selected_analysts == ("news",)
    assert buffer.selected_analysts == ["news"]
    plan_keys = [spec.key for spec in cli_run.build_analyst_execution_plan(buffer.selected_analysts).specs]
    assert plan_keys == ["news"]


@pytest.mark.unit
def test_deep_with_a_debate_env_override_shows_the_effective_config(monkeypatch, tmp_path, offline):
    """REQ-TA-FR-001: deep with TRADINGAGENTS_MAX_DEBATE_ROUNDS=1 -> debate 1, risk 3,
    tool cap 20, shown both on the terminal and in the report settings."""
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "1")
    buffer, graph = _drive(monkeypatch, tmp_path, "NVDA", "stock", profile="deep",
                           analysts_selection=["market", "social", "news", "fundamentals"])

    assert graph.conditional_logic.max_debate_rounds == 1
    assert graph.conditional_logic.max_risk_discuss_rounds == 3
    assert graph.graph_setup.max_tool_rounds == 20

    settings = graph.run_settings()
    assert (settings["max_debate_rounds"], settings["max_risk_discuss_rounds"],
            settings["max_tool_rounds"]) == (1, 3, 20)

    effective = [content for _ts, _kind, content in buffer.messages if content.startswith("Effective configuration")]
    assert effective, buffer.messages
    line = effective[0]
    assert "debate 1" in line and "risk 3" in line and "tool rounds per analyst 20" in line
    assert "profile deep" in line

    # The report shows the same effective numbers.
    state = {"trade_date": TRADE_DATE, "final_trade_decision": "**Rating**: Overweight",
             "market_report": "M"}
    md = graph.save_reports(state, "NVDA", save_path=tmp_path / "report", html=True).read_text(encoding="utf-8")
    header = md.split("## ")[0]
    assert "research debate rounds 1" in header
    assert "risk debate rounds 3" in header
    assert "tool rounds per analyst 20" in header


@pytest.mark.unit
def test_crypto_standard_drops_fundamentals(monkeypatch, tmp_path, offline):
    """REQ-TA-FR-001: BTC-USD with the standard profile drops fundamentals, and the
    graph and the terminal agree; the stock standard mapping is unchanged."""
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    # The menu, applying the crypto filter, offers the standard set without fundamentals.
    buffer, graph = _drive(monkeypatch, tmp_path, "BTC-USD", "crypto", profile="standard",
                           analysts_selection=["market", "social", "news"])

    assert "fundamentals" not in graph.selected_analysts
    assert set(graph.selected_analysts) == {"market", "social", "news"}
    assert buffer.selected_analysts == ["market", "social", "news"]
    # Round budgets still come from the standard profile.
    assert (graph.conditional_logic.max_debate_rounds,
            graph.conditional_logic.max_risk_discuss_rounds,
            graph.graph_setup.max_tool_rounds) == (1, 1, 20)

    # The stock standard mapping (which the profile keeps for stocks) still includes fundamentals.
    stock_graph = trading_graph.TradingAgentsGraph(
        ("market", "social", "news", "fundamentals"), config=copy.deepcopy(DEFAULT_CONFIG),
        profile="standard")
    assert stock_graph.selected_analysts == ("market", "social", "news", "fundamentals")


@pytest.mark.unit
def test_a_bare_profile_run_records_no_override(monkeypatch, tmp_path, offline):
    """REQ-TA-FR-001: NVDA --profile quick with no --analysts records no override."""
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    _buffer, graph = _drive(monkeypatch, tmp_path, "NVDA", "stock", profile="quick",
                            analysts_selection=["market", "news"])

    settings = graph.run_settings()
    assert settings["profile_requested"] == "quick"
    assert settings["profile_overrides"] == {}
    assert settings["profile_resolved"]["analysts"] == ["market", "news"]


@pytest.mark.unit
def test_an_explicit_analysts_flag_is_recorded(monkeypatch, tmp_path, offline):
    """REQ-TA-FR-001: --analysts market,news is recorded as an override even though it
    matches the quick profile's own set."""
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    _buffer, graph = _drive(monkeypatch, tmp_path, "NVDA", "stock", profile="quick",
                            analysts_selection=["market", "news"],
                            analysts_flag="market,news")

    settings = graph.run_settings()
    assert settings["profile_overrides"] == {"analysts": ["market", "news"]}
    assert settings["profile_resolved"]["analysts"] == ["market", "news"]


@pytest.mark.unit
def test_the_crypto_filtered_list_shows_in_resolved(monkeypatch, tmp_path, offline):
    """REQ-TA-FR-001: BTC-USD --profile standard records the filtered set in
    profile_resolved, and (no --analysts) records no override."""
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    _buffer, graph = _drive(monkeypatch, tmp_path, "BTC-USD", "crypto", profile="standard",
                            analysts_selection=["market", "social", "news"])

    settings = graph.run_settings()
    assert settings["profile_overrides"] == {}
    assert settings["profile_resolved"]["analysts"] == ["market", "social", "news"]
    assert "fundamentals" not in settings["profile_resolved"]["analysts"]
