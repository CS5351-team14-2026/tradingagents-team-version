"""Controlled failure: provider timeout ends with a defined status, no escape (REQ-TA-QR-001).

Offline test: a provider call that raises a timeout (``TimeoutError`` and the
provider SDK timeout classes) is a *classified* failure. ``propagate()`` records
``run_metadata.failure.code=PROVIDER_TIMEOUT`` + ``status=failed`` and returns a
controlled ``(state, REVIEW)`` instead of letting the exception escape. Uses
scripted models and the shared offline doubles; never the network.
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
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.failure import FailureCode, classify_exception
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"


class _TimeoutModel(upstream.ScriptedModel):
    """Raises a classified timeout on a chosen call, once."""

    def _count(self) -> None:
        self.calls.append(1)
        if len(self.calls) == self.fail_at:
            raise TimeoutError("provider read timed out")


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
def test_timeout_error_is_classified_provider_timeout():
    """REQ-TA-QR-001: TimeoutError and provider timeout classes map to PROVIDER_TIMEOUT."""
    assert classify_exception(TimeoutError("x")) == FailureCode.PROVIDER_TIMEOUT
    # A provider SDK timeout class, matched by name (no import needed).
    APITimeout = type("APITimeoutError", (Exception,), {})
    assert classify_exception(APITimeout("t")) == FailureCode.PROVIDER_TIMEOUT
    # An unrelated error is not misclassified.
    assert classify_exception(KeyError("boom")) is None


@pytest.mark.unit
def test_provider_timeout_returns_controlled_review(tmp_path, monkeypatch, offline):
    """REQ-TA-QR-001 (D-A): a provider timeout does not escape; the run ends REVIEW."""
    model = _TimeoutModel(structured=True, fail_at=10)  # past the analysts
    graph = _graph(tmp_path, monkeypatch, model)

    # No pytest.raises: the timeout must be handled into a controlled result.
    state, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == "REVIEW"
    assert state["final_rating"] == "REVIEW"
    assert state["run_failure"]["code"] == "PROVIDER_TIMEOUT"

    # The persisted run record carries the failure under status=failed.
    record_path = tmp_path / "r" / "NVDA" / "TradingAgentsStrategy_logs" / f"run_record_{TRADE_DATE}.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    assert data["run_metadata"]["status"] == "failed"
    assert data["run_metadata"]["failure"]["code"] == "PROVIDER_TIMEOUT"
    assert data["run_metadata"]["failure"]["exception_type"] == "TimeoutError"
    # No secret/path/URL in the safe diagnostic.
    diag = data["run_metadata"]["failure"]["diagnostic"].lower()
    assert "http" not in diag and "://" not in diag


@pytest.mark.unit
def test_unclassified_exception_still_raises(tmp_path, monkeypatch, offline):
    """REQ-TA-QR-001: only classified failures are controlled; a generic bug still raises."""
    model = upstream.ScriptedModel(structured=True, fail_at=10)  # raises RuntimeError
    graph = _graph(tmp_path, monkeypatch, model)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        graph.propagate("NVDA", TRADE_DATE)
