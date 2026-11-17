"""REQ-TA-FR-002/QR-003/004/005: durable accounting and recovery boundaries."""

import json

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from tradingagents.graph import trading_graph
from tradingagents.graph.checkpointer import (
    BudgetLedgerStore,
    checkpoint_step,
    clear_checkpoint,
    thread_id,
)
from tradingagents.llm_clients.invocation import CallSpec, invoke_with_budget
from tradingagents.run_budget import RunBudgetContext, RunBudgetTracker, UsageObservation

from . import test_budget_entrypoints as doubles

offline = doubles.offline
DATE = doubles.graph_doubles.TRADE_DATE


class PaidState(TypedDict):
    value: int


def _budget_graph(tmp_path, monkeypatch, model=None, limit=10000):
    graph = doubles._graph(tmp_path, monkeypatch, model or doubles.UsageModel())
    graph.config.update(token_budget=limit, checkpoint_enabled=True)
    return graph


@pytest.mark.unit
def test_fr002_budget_checkpoint_restores_cumulative_usage_and_same_run_identity(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel(fail_at=1)
    graph = _budget_graph(tmp_path, monkeypatch, model)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        graph.propagate("NVDA", DATE)
    first = graph._run_budget
    assert first.llm_calls > 0
    model.fail_at = 0
    graph.propagate("NVDA", DATE)
    final = graph._run_budget
    assert final.run_id == first.run_id
    # A failed historical request has unknown usage. Its replay is an optional
    # retry and must not dispatch while that uncertainty remains.
    assert final.llm_calls == first.llm_calls
    assert final.known_tokens >= (first.known_tokens or 0)
    assert final.total_tokens is None  # the failed historical attempt had no usage
    assert graph.run_settings()["run_metadata"]["budget"]["status"] == "BUDGET_WARNING"
    signature = graph._run_signature("stock")
    assert graph.run_settings()["run_metadata"]["status"] == "failed"
    assert checkpoint_step(graph.config["data_cache_dir"], "NVDA", DATE, signature) is not None
    assert BudgetLedgerStore(graph.config["data_cache_dir"], "NVDA",
                             thread_id("NVDA", DATE, signature)).load()["run_id"] == first.run_id


@pytest.mark.unit
def test_fr002_usage_committed_without_graph_checkpoint_is_never_silently_zeroed(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel()
    graph = _budget_graph(tmp_path, monkeypatch, model)
    with graph.observation_scope() as tracker:
        graph.begin_checkpoint("NVDA", DATE)
        tracker.finish_call("paid-before-checkpoint", UsageObservation(30, 20, state="complete"))
        graph.end_checkpoint()
    count = len(model.calls)
    state, signal = graph.propagate("NVDA", DATE)
    assert signal == "REVIEW" and len(model.calls) == count
    assert state["budget_termination"]["reason_codes"] == ["BUDGET_CHECKPOINT_MISMATCH"]
    meta = graph.run_settings()["run_metadata"]
    assert meta["status"] == "failed" and meta["total_tokens"] is None
    assert "BUDGET_CHECKPOINT_MISMATCH" in meta["budget"]["reason_codes"]
    assert graph.memory_log.get_pending_entries() == []


@pytest.mark.unit
def test_fr002_explicit_checkpoint_clear_authorizes_a_fresh_budget_identity(
        tmp_path, monkeypatch, offline):
    graph = _budget_graph(tmp_path, monkeypatch)
    with graph.observation_scope() as tracker:
        graph.begin_checkpoint("NVDA", DATE)
        old_run = tracker.run_id
        tracker.finish_call("orphan", UsageObservation(20, 10, state="complete"))
        graph.end_checkpoint()
    signature = graph._run_signature("stock")
    clear_checkpoint(graph.config["data_cache_dir"], "NVDA", DATE, signature)
    state, signal = graph.propagate("NVDA", DATE)
    assert signal == state["final_rating"] == "Overweight"
    assert graph._run_budget.run_id != old_run
    assert graph.run_settings()["run_metadata"]["status"] == "completed"


@pytest.mark.unit
def test_fr002_missing_ledger_refuses_resume_without_model_dispatch(tmp_path, monkeypatch, offline):
    model = doubles.UsageModel(fail_at=1)
    graph = _budget_graph(tmp_path, monkeypatch, model)
    with pytest.raises(RuntimeError):
        graph.propagate("NVDA", DATE)
    signature = graph._run_signature("stock")
    store = BudgetLedgerStore(graph.config["data_cache_dir"], "NVDA", thread_id("NVDA", DATE, signature))
    store.load()
    store.clear()
    count = len(model.calls)
    state, signal = graph.propagate("NVDA", DATE)
    assert signal == "REVIEW" and len(model.calls) == count
    assert state["budget_termination"]["reason_codes"] == ["BUDGET_HISTORY_UNAVAILABLE"]
    assert graph.run_settings()["run_metadata"]["status"] == "failed"


@pytest.mark.unit
def test_fr002_enabling_budget_cannot_treat_legacy_checkpoint_history_as_zero(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel(fail_at=1)
    graph = _budget_graph(tmp_path, monkeypatch, model, limit=None)
    with pytest.raises(RuntimeError):
        graph.propagate("NVDA", DATE)
    count = len(model.calls)
    graph.config["token_budget"] = 10000
    state, signal = graph.propagate("NVDA", DATE)
    assert signal == "REVIEW" and len(model.calls) == count
    assert state["budget_termination"]["reason_codes"] == ["BUDGET_HISTORY_UNAVAILABLE"]


@pytest.mark.unit
def test_fr002_checkpoint_restore_preserves_cli_tracker_instance(tmp_path, monkeypatch, offline):
    model = doubles.UsageModel(fail_at=1)
    graph = _budget_graph(tmp_path, monkeypatch, model)
    with pytest.raises(RuntimeError):
        graph.propagate("NVDA", DATE)
    old = graph._run_budget
    tracker = RunBudgetTracker(10000)
    with RunBudgetContext(tracker).activate(), graph.observation_scope():
        graph.begin_checkpoint("NVDA", DATE)
        try:
            assert graph._observation_context.tracker is tracker
            assert tracker.run_id == old.run_id
            assert tracker.snapshot().llm_calls == old.llm_calls
        finally:
            graph.end_checkpoint()


@pytest.mark.unit
def test_fr002_usage_between_graph_commits_survives_replay_and_success_cleanup(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel()
    graph = _budget_graph(tmp_path, monkeypatch, model)
    crash = [True]

    def paid_step(state):
        invoke_with_budget(model, "Offline paid step", call=CallSpec("paid_step", "required"))
        if crash[0]:
            raise RuntimeError("crashed after usage before graph commit")
        return {"value": state["value"] + 1}

    workflow = StateGraph(PaidState)
    workflow.add_node("paid", paid_step)
    workflow.add_edge(START, "paid")
    workflow.add_edge("paid", END)
    graph.workflow = workflow
    graph.graph = workflow.compile()
    with graph.observation_scope() as tracker:
        tid = graph.begin_checkpoint("NVDA", DATE)
        try:
            with pytest.raises(RuntimeError, match="crashed after usage"):
                graph.graph.invoke({"value": 0}, config={"configurable": {"thread_id": tid}})
            first = tracker.snapshot()
        finally:
            graph.end_checkpoint()
    crash[0] = False
    with graph.observation_scope() as tracker:
        tid2 = graph.begin_checkpoint("NVDA", DATE)
        try:
            assert tid2 == tid and tracker.run_id == first.run_id
            assert tracker.snapshot().total_tokens == 5
            assert graph.graph.invoke(None, config={"configurable": {"thread_id": tid2}}) == {"value": 1}
            assert tracker.snapshot().total_tokens == 10
            graph.clear_checkpoint_on_success("NVDA", DATE)
        finally:
            graph.end_checkpoint()
    assert BudgetLedgerStore(graph.config["data_cache_dir"], "NVDA", tid).load() is None


@pytest.mark.unit
def test_fr002_checkpoint_write_failure_is_controlled_before_dispatch(tmp_path, monkeypatch, offline):
    model = doubles.UsageModel()
    graph = _budget_graph(tmp_path, monkeypatch, model)

    def fail(*args):
        raise OSError("offline disk failure")

    monkeypatch.setattr(BudgetLedgerStore, "save_state", fail)
    state, signal = graph.propagate("NVDA", DATE)
    assert signal == "REVIEW" and not model.calls
    assert state["budget_termination"]["reason_codes"] == ["BUDGET_LEDGER_WRITE_FAILED"]
    log = next((tmp_path / "results").rglob("full_states_log_*.json"))
    assert json.loads(log.read_text(encoding="utf-8"))["run_settings"]["run_metadata"]["status"] == "failed"


@pytest.mark.unit
def test_fr002_budget_identity_changes_only_when_enabled(tmp_path, monkeypatch, offline):
    graph = _budget_graph(tmp_path, monkeypatch, limit=None)
    absent = dict(graph.config)
    absent.pop("token_budget")
    graph.config = absent
    historical = (graph._run_signature("stock"), graph._integration_run_signature("stock"))
    graph.config["token_budget"] = None
    assert historical == (graph._run_signature("stock"), graph._integration_run_signature("stock"))
    graph.config["token_budget"] = 0
    zero = graph._run_signature("stock")
    graph.config["token_budget"] = 1
    assert graph._run_signature("stock") != zero != historical[0]
    monkeypatch.setattr(trading_graph, "BUDGET_STATE_VERSION", 999)
    assert graph._run_signature("stock") != zero
