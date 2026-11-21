"""Controlled failure: stock data unavailable -> REVIEW + STOCK_DATA_UNAVAILABLE (REQ-TA-QR-001).

End-to-end, offline: when the CORE market data (prices / indicators / verified
snapshot) cannot be served, the run must not present a confident tradeable call.
Per ADR-005 D-D1 the result is downgraded to ``REVIEW`` (lifecycle ``completed``,
a caveated report was produced) and the run record carries
``run_metadata.failure.code = STOCK_DATA_UNAVAILABLE``. No exception escapes.

Also keeps the lower-level checks: the router returns one explicit sentinel, and
the failure block is fixed + safe.
"""

from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

from offline import test_graph_end_to_end as upstream
from tradingagents.agents import context
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"


# ---------------------------------------------------------------- lower level

@pytest.mark.unit
def test_no_data_sentinel_and_safe_block():
    """REQ-TA-QR-001: one explicit sentinel, and a fixed safe failure block."""
    from tradingagents.failure import FailureCode, build_failure

    sentinel = router.no_data_available(NoMarketDataError("NVDA", "NVDA", "no rows"))
    assert sentinel.startswith("NO_DATA_AVAILABLE")
    unavail = router.vendor_unavailable("get_stock_data", VendorUnavailableError("429"))
    assert unavail.startswith("DATA_UNAVAILABLE")

    block = build_failure(FailureCode.STOCK_DATA_UNAVAILABLE, phase="analysis")
    assert block["code"] == "STOCK_DATA_UNAVAILABLE"
    assert "http" not in block["diagnostic"].lower()


# --------------------------------------------------------------- end to end

@pytest.fixture
def core_data_down(monkeypatch, tmp_path):
    """Every vendor answers EXCEPT core market data, which is unavailable."""
    for method, vendors in router.VENDOR_METHODS.items():
        for vendor in vendors:
            if method in {"get_stock_data", "get_indicators"}:
                def _no_data(*a, _m=method, **k):
                    raise NoMarketDataError("NVDA", "NVDA", "no rows")
                monkeypatch.setitem(vendors, vendor, _no_data)
            else:
                monkeypatch.setitem(vendors, vendor, lambda *a, _m=method, **k: f"{_m} data")

    def _snapshot_down(*a, **k):
        raise NoMarketDataError("NVDA", "NVDA", "no price rows")

    monkeypatch.setattr(snapshot, "load_ohlcv", _snapshot_down)
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
def test_core_data_unavailable_downgrades_to_review(tmp_path, monkeypatch, core_data_down):
    """REQ-TA-QR-001 (D-D1): missing core market data -> REVIEW + record, no exception."""
    graph = _graph(tmp_path, monkeypatch, upstream.ScriptedModel(structured=True))

    state, signal = graph.propagate("NVDA", TRADE_DATE)  # must not raise

    assert signal == "REVIEW"
    assert state["final_rating"] == "REVIEW"

    meta = graph.run_settings()["run_metadata"]
    assert meta["status"] == "completed"      # D-D: caveated report produced
    assert meta["failure"]["code"] == "STOCK_DATA_UNAVAILABLE"
    json.dumps(meta)                          # record is JSON-safe


@pytest.mark.unit
def test_available_data_does_not_record_the_failure(tmp_path, monkeypatch):
    """REQ-TA-QR-001: when data is available, no STOCK_DATA_UNAVAILABLE is recorded."""
    # Reuse the standard all-vendors-offline fixture from the e2e module.
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

    graph = _graph(tmp_path, monkeypatch, upstream.ScriptedModel(structured=True))
    _state, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == "Overweight"
    meta = graph.run_settings()["run_metadata"]
    assert "failure" not in meta
