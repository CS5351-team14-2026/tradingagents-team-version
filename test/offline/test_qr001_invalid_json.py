"""Controlled failure: invalid agent JSON ends with a defined status, no escape (REQ-TA-QR-001).

Offline tests covering both shapes of "an agent returned invalid JSON":

1. A structured-output parse error (``pydantic.ValidationError`` / ``JSONDecodeError``)
   raised where nothing catches it is *classified* and turned into a controlled
   ``(state, REVIEW)`` with ``run_metadata.failure.code=INVALID_AGENT_JSON`` —
   it never escapes as an uncaught exception.
2. The structured Portfolio-Manager path already degrades (retry -> free-text
   fallback) without raising; that degradation must not fabricate a tradeable
   recommendation.

Uses scripted models and the shared offline doubles; never the network.
"""

from __future__ import annotations

import copy
import json

import pandas as pd
import pytest
from pydantic import BaseModel, ValidationError

from offline import test_graph_end_to_end as upstream
from tradingagents.agents import context
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.agents.structured import invoke_structured, invoke_structured_or_freetext
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.failure import FailureCode, classify_exception
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"


class _InvalidJsonModel(upstream.ScriptedModel):
    """Raises a ValidationError (invalid structured payload) on a chosen call, once."""

    def _count(self) -> None:
        self.calls.append(1)
        if len(self.calls) == self.fail_at:
            raise ValidationError.from_exception_data(
                "AIMessage", [{"type": "missing", "loc": ("rating",), "input": {}}]
            )


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
def test_json_parse_errors_are_classified_invalid_json():
    """REQ-TA-QR-001: ValidationError/JSONDecodeError map to INVALID_AGENT_JSON."""
    import json as _json

    err = ValidationError.from_exception_data(
        "X", [{"type": "missing", "loc": ("a",), "input": {}}])
    assert classify_exception(err) == FailureCode.INVALID_AGENT_JSON
    try:
        _json.loads("{not json")
    except _json.JSONDecodeError as exc:
        assert classify_exception(exc) == FailureCode.INVALID_AGENT_JSON


@pytest.mark.unit
def test_invalid_json_returns_controlled_review(tmp_path, monkeypatch, offline):
    """REQ-TA-QR-001 (D-A): an escaping parse error does not crash; the run ends REVIEW."""
    model = _InvalidJsonModel(structured=True, fail_at=10)  # a non-structured analyst turn
    graph = _graph(tmp_path, monkeypatch, model)

    state, signal = graph.propagate("NVDA", TRADE_DATE)  # must not raise

    assert signal == "REVIEW"
    assert state["run_failure"]["code"] == "INVALID_AGENT_JSON"
    record_path = tmp_path / "r" / "NVDA" / "TradingAgentsStrategy_logs" / f"run_record_{TRADE_DATE}.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    assert data["run_metadata"]["status"] == "failed"
    assert data["run_metadata"]["failure"]["code"] == "INVALID_AGENT_JSON"
    assert data["run_metadata"]["failure"]["exception_type"] == "ValidationError"


class _Schema(BaseModel):
    value: int


@pytest.mark.unit
def test_structured_path_degrades_without_raising():
    """REQ-TA-FR-002/QR-001: a failing structured call falls back; no fabricated call."""
    class _AlwaysBad:
        def invoke(self, *_a, **_k):
            raise ValidationError.from_exception_data(
                "X", [{"type": "missing", "loc": ("value",), "input": {}}])

    # Structured call keeps failing -> returns None after the gated retry.
    assert invoke_structured(_AlwaysBad(), "p", "Agent") is None

    # Free-text fallback raises a classified error -> controlled empty report, no raise.
    class _PlainBad:
        def invoke(self, *_a, **_k):
            try:
                json.loads("{bad")
            except json.JSONDecodeError as exc:
                raise exc

    out = invoke_structured_or_freetext(None, _PlainBad(), "p", str, "Agent")
    assert out == ""
