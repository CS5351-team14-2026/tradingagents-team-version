"""Checkpoint setup and cleanup failures (REQ-TA-FR-002 D5/D8; QR-004)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from tradingagents.graph import trading_graph
from tradingagents.graph.checkpointer import BudgetLedgerStore
from tradingagents.llm_clients.invocation import CallSpec, invoke_with_budget
from tradingagents.run_budget import (
    BudgetLedgerError,
    RunBudgetContext,
    RunBudgetTracker,
    current_run_context,
)

from . import (
    test_budget_checkpoint as checkpoint_doubles,
    test_budget_entrypoints as budget_doubles,
    test_cli_profile_e2e as cli_doubles,
)

offline = budget_doubles.offline
DATE = checkpoint_doubles.DATE


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["saver-enter", "compile", "checkpoint-lookup"])
def test_fr002_public_checkpoint_setup_failure_restores_scope_and_connections(
        tmp_path, monkeypatch, offline, failure):
    """REQ-TA-FR-002 D5/D8: failed setup cannot leak a run into the next caller."""
    graph = checkpoint_doubles._budget_graph(tmp_path, monkeypatch)
    original_compile = graph.workflow.compile
    original_saver = trading_graph.get_checkpointer
    original_lookup = trading_graph.checkpoint_step
    opened, closed = [], []

    @contextmanager
    def saver(data_dir, ticker):
        if failure == "saver-enter":
            raise RuntimeError("fixture saver entry failure")
        with original_saver(data_dir, ticker) as value:
            opened.append(value)
            try:
                yield value
            finally:
                closed.append(value)

    def compile_graph(*args, **kwargs):
        if failure == "compile" and kwargs.get("checkpointer") is not None:
            raise RuntimeError("fixture compilation failure")
        return original_compile(*args, **kwargs)

    def lookup(*args, **kwargs):
        if failure == "checkpoint-lookup":
            raise RuntimeError("fixture checkpoint lookup failure")
        return original_lookup(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(trading_graph, "get_checkpointer", saver)
        patch.setattr(graph.workflow, "compile", compile_graph)
        patch.setattr(trading_graph, "checkpoint_step", lookup)
        with pytest.raises(RuntimeError, match="fixture"):
            graph.begin_checkpoint("NVDA", DATE)
        assert current_run_context() is None
        assert getattr(graph, "_observation_context", None) is None
        assert graph._checkpointer_ctx is None
        assert getattr(graph, "_checkpoint_observation_scope", None) is None
        assert not graph._resuming
        assert getattr(graph, "_thread_id", None) is None
        assert len(closed) == len(opened)
    # The same graph can start a separate run after setup's infrastructure is
    # available again. No failed context or open saver is reused.
    graph.begin_checkpoint("NVDA", DATE)
    graph.end_checkpoint()
    assert current_run_context() is None


@pytest.mark.unit
def test_fr002_public_begin_with_external_budget_restores_cumulative_history(
        tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002 D8: an external N works with the default None config."""
    model = budget_doubles.UsageModel()
    graph = checkpoint_doubles._budget_graph(tmp_path, monkeypatch, model, limit=None)
    crash = [True]

    def paid_step(state):
        invoke_with_budget(model, "Offline paid node", call=CallSpec("external_required", "required"))
        if crash[0]:
            raise RuntimeError("fixture interruption after usage")
        return {"value": state["value"] + 1}

    workflow = StateGraph(checkpoint_doubles.PaidState)
    workflow.add_node("paid", paid_step)
    workflow.add_edge(START, "paid")
    workflow.add_edge("paid", END)
    graph.workflow = workflow
    graph.graph = workflow.compile()
    first = RunBudgetTracker(100)
    external = RunBudgetContext(first)
    with external.activate():
        tid = graph.begin_checkpoint("NVDA", DATE)
        try:
            assert graph._effective_budget_limit() == 100
            assert graph._observation_context is external
            with pytest.raises(RuntimeError, match="fixture interruption"):
                graph.graph.invoke({"value": 0}, config={"configurable": {"thread_id": tid}})
            assert first.snapshot().total_tokens == 5
        finally:
            graph.end_checkpoint()
        assert current_run_context() is external
    assert current_run_context() is None
    crash[0] = False
    second = RunBudgetTracker(100)
    external = RunBudgetContext(second)
    with external.activate():
        tid2 = graph.begin_checkpoint("NVDA", DATE)
        try:
            assert tid2 == tid
            assert second.run_id == first.run_id
            assert second.snapshot().total_tokens == 5
            assert graph.graph.invoke(None, config={"configurable": {"thread_id": tid2}}) == {"value": 1}
            assert second.snapshot().total_tokens == 10
            graph.clear_checkpoint_on_success("NVDA", DATE)
        finally:
            graph.end_checkpoint()
    assert current_run_context() is None


def _clear_failure(self):
    raise BudgetLedgerError("BUDGET_LEDGER_CLEAR_FAILED")


def _assert_cleanup_result(graph, limit):
    meta = graph.run_settings()["run_metadata"]
    assert meta["status"] == "completed"
    assert meta["usage_complete"] is True
    assert meta["budget"]["status"] == ("BUDGET_EXHAUSTED" if limit == 0 else "BUDGET_WARNING")
    assert "BUDGET_LEDGER_CLEAR_FAILED" in meta["budget"]["reason_codes"]
    entries = graph.memory_log.load_entries()
    assert len(entries) == 1 and entries[0]["rating"] == "Overweight"
    paths = list((Path(graph.config["results_dir"]) / "NVDA").rglob("*.json"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    persisted = [value.get("run_settings", value).get("run_metadata") for value in records]
    assert persisted
    assert all(value == meta for value in persisted if value is not None)
    assert current_run_context() is None


@pytest.mark.unit
@pytest.mark.parametrize("limit", [10000, 0], ids=["warning", "exhaustion-precedence"])
def test_fr002_direct_graph_cleanup_failure_keeps_valid_result_and_honest_metadata(
        tmp_path, monkeypatch, offline, limit):
    """REQ-TA-FR-002/QR-004: cleanup error does not discard a valid recommendation."""
    graph = checkpoint_doubles._budget_graph(tmp_path, monkeypatch, limit=limit)
    monkeypatch.setattr(BudgetLedgerStore, "clear", _clear_failure)
    state, signal = graph.propagate("NVDA", DATE)
    assert signal == state["final_rating"] == "Overweight"
    assert not state.get("budget_termination")
    _assert_cleanup_result(graph, limit)


@pytest.mark.unit
@pytest.mark.parametrize("limit", [10000, 0], ids=["warning", "exhaustion-precedence"])
def test_fr002_cli_cleanup_failure_keeps_valid_result_and_matches_direct_graph_contract(
        tmp_path, monkeypatch, offline, limit):
    """REQ-TA-FR-002/QR-004: CLI cleanup has the same completed/usage semantics."""
    model = budget_doubles.UsageModel()
    monkeypatch.setattr(trading_graph, "create_tier_client", budget_doubles._client_factory(model))
    monkeypatch.setitem(cli_doubles.DEFAULT_CONFIG, "checkpoint_enabled", True)
    monkeypatch.setitem(cli_doubles.DEFAULT_CONFIG, "token_budget", limit)
    monkeypatch.setattr(BudgetLedgerStore, "clear", _clear_failure)
    buffer, graph = cli_doubles._drive(
        monkeypatch, tmp_path, "NVDA", "stock", "quick", ["market", "news"])
    assert any("Completed analysis" in content for _stamp, _kind, content in buffer.messages)
    _assert_cleanup_result(graph, limit)
