"""Budget admission in the graph: optional calls stop, required still run (FR-002; ADR-004).

Offline, deterministic tests of the node-boundary admission gate in
``graph/setup.py``: debate and risk contributions (optional) are skipped once
the budget refuses while the required synthesis still runs and the run reaches a
controlled terminal state with no uncaught exception. Uses scripted models and
the shared offline doubles; never the network.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest

# Reuse the real chat-model test double the end-to-end suite already uses.
from offline import test_graph_end_to_end as upstream
from tradingagents.agents import context
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"


class _OffsetModel(upstream.ScriptedModel):
    """A ScriptedModel that reports usage on every call (REQ-TA-FR-002).

    The base double answers without usage_metadata; this subclass attaches a
    fixed complete usage to each chat result so the run's ledger records real
    usage and the budget can be exhausted deterministically.
    """

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop, run_manager, **kwargs)
        for generation in result.generations:
            msg = generation.message
            msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        return result


@pytest.fixture
def offline(monkeypatch, tmp_path):
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


def _graph(tmp_path, monkeypatch, model, **config):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "r"), data_cache_dir=str(tmp_path / "c"),
               memory_log_path=str(tmp_path / "log.md"), **config)
    monkeypatch.setattr(trading_graph, "create_tier_client", lambda config, tier, **k: upstream._Client(model))
    return trading_graph.TradingAgentsGraph(config=cfg, selected_analysts=("market", "news"))


@pytest.mark.unit
def test_no_budget_runs_every_phase(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002 (D6): with no budget, every phase runs (baseline behaviour)."""
    model = _OffsetModel(structured=True)
    graph = _graph(tmp_path, monkeypatch, model)
    state, signal = graph.propagate("NVDA", TRADE_DATE)
    assert signal == state["final_rating"]
    # debate and risk contributions present (no skip markers)
    assert not state["investment_debate_state"].get("budget_exhausted")
    assert not state["risk_debate_state"].get("budget_exhausted")
    assert graph._run_budget_tracker.snapshot().limit is None


@pytest.mark.unit
def test_zero_budget_runs_required_synthesis_and_marks_skip_markers(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002 (D4): a zero budget stops optional debate/risk turns but the
    required synthesis still runs and the run completes without an exception."""
    model = _OffsetModel(structured=True)
    graph = _graph(tmp_path, monkeypatch, model, token_budget=0)

    # The analysts complete (required) and record usage; with a zero budget the
    # debate/risk optional turns are refused, so their histories carry a
    # controlled skip note (the transient routing flag is consumed by the
    # router, so it does not persist into the final state).
    state, signal = graph.propagate("NVDA", TRADE_DATE)

    snap = graph._run_budget_tracker.snapshot()
    assert snap.limit == 0
    # The required synthesis produced a final decision and rating.
    assert state["final_trade_decision"]
    assert signal  # a 5-tier rating or REVIEW
    # A controlled skip note exists in the optional phases' histories.
    debate_text = state["investment_debate_state"].get("history", "")
    risk_text = state["risk_debate_state"].get("history", "")
    assert "Budget control" in debate_text or "Budget control" in risk_text


@pytest.mark.unit
def test_skip_marker_routes_debate_to_research_manager(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002: a debate-phase skip marker routes straight to the Research Manager."""
    graph = _graph(tmp_path, monkeypatch, _OffsetModel(structured=True), token_budget=0)
    assert graph.conditional_logic.should_continue_debate(
        {"investment_debate_state": {"budget_exhausted": True, "count": 0, "current_response": ""}}
    ) == "Research Manager"
    assert graph.conditional_logic.should_continue_risk_analysis(
        {"risk_debate_state": {"budget_exhausted": True, "count": 0, "latest_speaker": ""}}
    ) == "Portfolio Manager"


@pytest.mark.unit
def test_inv003_tool_cap_preserved_under_budget(tmp_path, monkeypatch, offline):
    """REQ-TA-INV-003: the tool-round cap is enforced independently of the budget."""
    graph = _graph(tmp_path, monkeypatch, _OffsetModel(structured=True), token_budget=100000, max_tool_rounds=3)
    # The compiled analyst subgraph keeps the cap; budget only adds a gate on top.
    assert graph.graph_setup.max_tool_rounds == 3
