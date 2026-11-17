"""Concurrent in-flight calls retain their semantics (REQ-TA-FR-002; ADR-003)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from tradingagents.llm_clients.invocation import (
    BudgetInvocationRefused,
    CallSpec,
    invoke_with_budget,
)
from tradingagents.run_budget import CallRole, RunBudgetContext, RunBudgetTracker

from . import test_budget_entrypoints as budget_doubles, test_graph_end_to_end as graph_doubles

offline = graph_doubles.offline


class InFlightModel:
    def __init__(self):
        self.started = Barrier(3)
        self.finish = Event()
        self.lock = Lock()
        self.calls = []

    def invoke(self, prompt, config=None):
        with self.lock:
            self.calls.append(prompt)
        self.started.wait(timeout=10)
        assert self.finish.wait(timeout=10), "The test did not release in-flight requests"
        return AIMessage(content="Existing request finished", usage_metadata={
            "input_tokens": 5, "output_tokens": 3, "total_tokens": 8})


@pytest.mark.unit
def test_fr002_parallel_admitted_calls_can_collectively_overshoot_then_block_new_calls():
    """REQ-TA-FR-002: already started requests finish; no cancellation/hard cap claim."""
    tracker = RunBudgetTracker(10)
    context = RunBudgetContext(tracker)
    model = InFlightModel()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke_with_budget, model, f"request {i}", context=context,
                               call=CallSpec(phase="research.parallel", role=CallRole.OPTIONAL))
                   for i in range(2)]
        try:
            model.started.wait(timeout=10)
            assert tracker.snapshot().pending_calls == 2
        finally:
            model.finish.set()
        for future in futures:
            future.result(timeout=10)

    assert tracker.snapshot().known_tokens == 16 > tracker.limit
    with pytest.raises(BudgetInvocationRefused):
        invoke_with_budget(model, "must not dispatch", context=context,
                           call=CallSpec(phase="research.parallel", role=CallRole.OPTIONAL))
    assert len(model.calls) == 2


class ParallelUsageModel(budget_doubles.UsageModel):
    gate: Any

    def _generate(self, messages, *args, **kwargs):
        # All three tool-using initial analyst requests must overlap. Their
        # initial contributions remain required even at a tiny run budget.
        if self.tools and not isinstance(messages[-1], ToolMessage):
            self.gate.wait(timeout=10)
        return super()._generate(messages, *args, **kwargs)


@pytest.mark.unit
def test_fr002_budget_keeps_parallel_initial_analysts(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-003: budget enforcement preserves parallel analyst dispatch."""
    model = ParallelUsageModel(gate=Barrier(3))
    graph = budget_doubles._graph(tmp_path, monkeypatch, model)
    tracker = RunBudgetTracker(1)
    with RunBudgetContext(tracker).activate():
        state, signal = graph.propagate("NVDA", graph_doubles.TRADE_DATE)

    assert signal == "Overweight"
    assert len(model.threads) > 1
    assert state["investment_debate_state"]["budget_skipped"] is True
    assert state["risk_debate_state"]["budget_skipped"] is True
    assert tracker.snapshot().known_tokens > tracker.limit
    assert tracker.snapshot().usage_complete is True
