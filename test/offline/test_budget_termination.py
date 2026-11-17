"""REQ-TA-FR-002/QR-001/QR-004/INV-001: controlled budget failure."""

import json

import pytest
from langchain_core.runnables import RunnableLambda

from tradingagents.graph import trading_graph
from tradingagents.run_budget import RunBudgetContext, RunBudgetTracker

from . import test_budget_entrypoints as doubles

offline = doubles.offline


class MissedSynthesis(doubles.UsageModel):
    def with_structured_output(self, schema, **kwargs):
        return self | RunnableLambda(lambda message: None)


@pytest.mark.unit
@pytest.mark.parametrize("debug", [False, True])
def test_fr002_required_synthesis_failure_is_diagnostic_review_without_uncaught_error(
        tmp_path, monkeypatch, offline, debug):
    model = MissedSynthesis()
    graph = doubles._graph(tmp_path, monkeypatch, model)
    graph.debug = debug
    tracker = RunBudgetTracker(0)
    with RunBudgetContext(tracker).activate():
        state, signal = graph.propagate("NVDA", doubles.graph_doubles.TRADE_DATE)
    assert signal == state["final_rating"] == "REVIEW"
    assert state["budget_termination"]["reason_codes"]
    assert "could not produce a valid final recommendation" in state["final_trade_decision"]
    assert graph.run_settings()["run_metadata"]["status"] == "failed"
    assert graph.memory_log.get_pending_entries() == []
    state_log = next((tmp_path / "results").rglob("full_states_log_*.json"))
    persisted = json.loads(state_log.read_text(encoding="utf-8"))
    assert persisted["run_settings"]["run_metadata"]["status"] == "failed"
    assert persisted["final_rating"] == "REVIEW"
    assert persisted["budget_termination"] == state["budget_termination"]


@pytest.mark.unit
def test_fr002_cli_stream_keeps_controlled_failure_status_and_report(tmp_path, monkeypatch, offline):
    model = MissedSynthesis()
    monkeypatch.setattr(trading_graph, "create_tier_client", doubles._client_factory(model))
    monkeypatch.setattr(doubles.cli_doubles._Buffer, "update_agent_status",
                        lambda self, name, status: self.agent_status.__setitem__(name, status))
    with RunBudgetContext(RunBudgetTracker(0)).activate():
        buffer, graph = doubles.cli_doubles._drive(
            monkeypatch, tmp_path, "NVDA", "stock", "quick", ["market", "news"])
    assert graph.run_settings()["run_metadata"]["status"] == "failed"
    assert graph.memory_log.get_pending_entries() == []
    assert any("ended for review" in message for _, _, message in buffer.messages)
    assert buffer.agent_status.get("Portfolio Manager") != "completed"
    assert buffer.agent_status.get("Aggressive Analyst") != "completed"
