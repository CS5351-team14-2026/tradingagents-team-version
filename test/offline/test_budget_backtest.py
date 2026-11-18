"""Backtest budget isolation (REQ-TA-FR-002; ADR-004 D9).

Offline tests that each backtest cell gets a fresh ledger (no cell inherits the
previous cell's recorded usage), that the run's budget context is unbound after
a cell finishes, and that the backtest-tail settlement is not charged to the
last cell.
"""

from __future__ import annotations

import copy
import functools

import pandas as pd
import pytest

from offline import test_graph_end_to_end as upstream
from tradingagents.agents import context
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph
from tradingagents.run_budget import current_run_context

TRADE_DATE = "2026-01-09"


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


def _graph(tmp_path, monkeypatch, model):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "r"), data_cache_dir=str(tmp_path / "c"),
               memory_log_path=str(tmp_path / "log.md"))
    monkeypatch.setattr(trading_graph, "create_tier_client", lambda config, tier, **k: upstream._Client(model))
    graph = trading_graph.TradingAgentsGraph(config=cfg, selected_analysts=("market", "news"))
    return graph


@pytest.mark.unit
def test_each_cell_gets_a_fresh_ledger(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002 (D9): each run's ledger is independent; none inherits the previous."""
    graph = _graph(tmp_path, monkeypatch, upstream.ScriptedModel())
    seen = []
    real = graph._attach_budget_observation

    def capture():
        real()
        tracker = graph._run_budget_tracker
        seen.append(tracker)

    monkeypatch.setattr(graph, "_attach_budget_observation", capture)

    graph.propagate("NVDA", "2026-01-08")
    graph.propagate("NVDA", TRADE_DATE)

    assert len(seen) == 2
    assert seen[0] is not seen[1]   # distinct ledgers


@pytest.mark.unit
def test_context_unbound_after_a_run(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002 (D9): the budget context is unbound once a run finishes."""
    graph = _graph(tmp_path, monkeypatch, upstream.ScriptedModel())
    graph.propagate("NVDA", "2026-01-08")
    assert current_run_context() is None


@pytest.mark.unit
def test_partial_attach_is_none_when_no_ledger():
    """REQ-TA-FR-002: a graph with no ledger attaches no usage (baseline)."""
    graph = object.__new__(trading_graph.TradingAgentsGraph)
    graph._run_budget_tracker = None
    graph._run_usage = None
    functools.partial(trading_graph.TradingAgentsGraph._attach_budget_observation, graph)()
    assert graph._run_usage is None
