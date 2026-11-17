"""REQ-TA-FR-002/QR-004/005: analysis cells and tail reflection are isolated."""

import json

import pytest

from tradingagents import backtest
from tradingagents.graph import trading_graph

from . import test_budget_entrypoints as doubles
from .test_budget_termination import MissedSynthesis

offline = doubles.offline


@pytest.mark.unit
@pytest.mark.parametrize("model_type, expected", [(doubles.UsageModel, 2), (MissedSynthesis, 0)])
def test_fr002_backtest_budget_is_per_cell_and_controlled_failures_are_not_successes(
        tmp_path, monkeypatch, offline, model_type, expected):
    model = model_type()
    template = doubles._graph(tmp_path, monkeypatch, model)
    config = {**template.config, "token_budget": 0}
    captured = []
    original = trading_graph.TradingAgentsGraph

    class Captured(original):
        def propagate(self, *args, **kwargs):
            result = super().propagate(*args, **kwargs)
            captured.append(self._run_budget)
            return result

    monkeypatch.setattr(backtest, "TradingAgentsGraph", Captured)
    result = backtest.run_backtest(["NVDA"], ["2026-01-08", "2026-01-09"], config)
    assert result.cells_run == expected
    assert len(result.failures) == 2 - expected
    assert len(captured) == 2
    assert captured[0].run_id != captured[1].run_id
    assert captured[0].llm_calls == captured[1].llm_calls
    assert all(snapshot.limit == 0 and snapshot.blocked_calls > 0 for snapshot in captured)
    records = list((tmp_path / "results" / "backtest").rglob("settlements/*.json"))
    assert records
    tail = json.loads(records[-1].read_text(encoding="utf-8"))
    assert tail["replayable_settings"] == {"operation": "settlement", "token_budget": 0}
    assert tail["run_metadata"]["budget"]["limit"] == 0


@pytest.mark.unit
def test_fr002_standalone_reflection_record_does_not_overwrite_analysis_metadata(
        tmp_path, monkeypatch, offline):
    graph = doubles._graph(tmp_path, monkeypatch, doubles.UsageModel())
    graph.config["token_budget"] = 0
    graph.propagate("NVDA", doubles.graph_doubles.TRADE_DATE)
    analysis = graph.run_settings()
    graph.settle_pending("NVDA")
    assert graph.run_settings() == analysis
    standalone = graph.last_settlement_record
    assert standalone["run_metadata"]["budget"]["limit"] == 0
    assert standalone["run_metadata"]["llm_calls"] == 0
    assert (tmp_path / "results" / "settlements").is_dir()
