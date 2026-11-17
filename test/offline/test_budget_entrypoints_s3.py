"""REQ-TA-FR-002: public stream and checkpoint APIs enforce configured budgets."""

import pytest

from tradingagents.graph.checkpointer import BudgetLedgerStore
from tradingagents.run_budget import current_run_context

from . import test_budget_entrypoints as doubles

offline = doubles.offline
DATE = doubles.graph_doubles.TRADE_DATE


def _stream(graph, state, thread_id=None):
    args = graph.propagator.get_graph_args()
    if thread_id is not None:
        args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = thread_id
    final = {}
    for _, chunk in graph.stream_run(graph.checkpoint_input(state), **args):
        if chunk:
            final.update(chunk)
    return final


def _assert_zero_budget_enforced(graph, state, model):
    assert state["investment_debate_state"]["count"] == 0
    assert state["risk_debate_state"]["count"] == 0
    assert state["investment_debate_state"]["budget_skipped"] is True
    assert state["risk_debate_state"]["budget_skipped"] is True
    assert state["final_rating"] == "Overweight"
    metadata = graph.run_settings()["run_metadata"]
    assert metadata["budget"]["status"] == "BUDGET_EXHAUSTED"
    assert metadata["llm_calls"] == len(model.calls)
    assert metadata["total_tokens"] == 5 * len(model.calls) > 0


@pytest.mark.unit
def test_fr002_direct_public_stream_creates_budget_context_and_restores_caller(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel()
    graph = doubles._graph(tmp_path, monkeypatch, model)
    graph.config["token_budget"] = 0
    initial = graph.create_run_state("NVDA", DATE)

    assert current_run_context() is None
    state = _stream(graph, initial)

    assert current_run_context() is None
    _assert_zero_budget_enforced(graph, state, model)


@pytest.mark.unit
def test_fr002_public_begin_stream_end_needs_no_manual_observation_scope(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel()
    graph = doubles._graph(tmp_path, monkeypatch, model)
    graph.config.update(token_budget=0, checkpoint_enabled=True)
    initial = graph.create_run_state("NVDA", DATE)

    assert current_run_context() is None
    try:
        checkpoint_id = graph.begin_checkpoint("NVDA", DATE)
        context = current_run_context()
        assert checkpoint_id is not None and context is not None
        assert context.tracker.limit == 0
        state = _stream(graph, initial, checkpoint_id)
        assert current_run_context() is context
        _assert_zero_budget_enforced(graph, state, model)
        saved = BudgetLedgerStore(graph.config["data_cache_dir"], "NVDA", checkpoint_id).load()
        assert saved["run_id"] == context.tracker.run_id
        assert saved["calls"]
        graph.clear_checkpoint_on_success("NVDA", DATE)
    finally:
        graph.end_checkpoint()

    assert current_run_context() is None
    assert graph._checkpointer_ctx is None
    _assert_zero_budget_enforced(graph, state, model)


@pytest.mark.unit
def test_fr002_public_checkpoint_error_still_restores_automatic_context(
        tmp_path, monkeypatch, offline):
    model = doubles.UsageModel(fail_at=1)
    graph = doubles._graph(tmp_path, monkeypatch, model)
    graph.config.update(token_budget=10000, checkpoint_enabled=True)
    initial = graph.create_run_state("NVDA", DATE)

    try:
        checkpoint_id = graph.begin_checkpoint("NVDA", DATE)
        with pytest.raises(RuntimeError, match="provider unavailable"):
            _stream(graph, initial, checkpoint_id)
    finally:
        graph.end_checkpoint()

    assert current_run_context() is None
    assert graph._checkpointer_ctx is None
