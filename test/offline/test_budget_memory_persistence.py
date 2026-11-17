"""Settlement accounting-failure records (REQ-TA-FR-002/QR-001/QR-004/QR-005)."""

from __future__ import annotations

import json
import logging

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.usage import UsageCallbackHandler
from tradingagents.memory import TradingMemoryLog, settlement
from tradingagents.memory.reflection import Reflector
from tradingagents.run_budget import (
    BudgetLedgerError,
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
    current_run_context,
)

from .test_budget_entrypoints import UsageModel


def _graph(tmp_path, model, limit=100):
    """Real public graph settlement/record methods with existing offline doubles."""
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"results_dir": str(tmp_path / "results"), "token_budget": limit,
                    "memory_log_path": str(tmp_path / "memory.md")}
    graph.selected_analysts = ("market",)
    graph.memory_log = TradingMemoryLog(graph.config)
    graph.reflector = Reflector(model)
    return graph


@pytest.fixture
def mature_returns(monkeypatch):
    calls = []

    def fetch(ticker, date, holding_days=5, benchmark="SPY"):
        calls.append((ticker, date))
        return 0.05, 0.02, holding_days, "2026-02-02"

    monkeypatch.setattr(settlement, "fetch_returns", fetch)
    return calls


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["settle_pending", "settle_all_pending"])
def test_fr002_settlement_ledger_failure_propagates_without_provider_failure_or_later_attempts(
        tmp_path, mature_returns, caplog, operation):
    """REQ-TA-FR-002/QR-001: failed durable admission cannot turn into a provider retry."""
    model = UsageModel()
    graph = _graph(tmp_path, model)
    graph.memory_log.store_decision("AAPL", "2026-01-05", "Rating: Buy")
    graph.memory_log.store_decision("AAPL", "2026-01-12", "Rating: Buy")
    graph.memory_log.store_decision("MSFT", "2026-01-05", "Rating: Buy")
    tracker = RunBudgetTracker(100)
    writes = []

    def writer(state):
        writes.append(state)
        if state["calls"]:
            raise BudgetLedgerError("BUDGET_LEDGER_WRITE_FAILED")

    tracker.bind_persistence(writer)
    args = ["AAPL"] if operation == "settle_pending" else []
    with (RunBudgetContext(tracker).activate(), caplog.at_level(logging.WARNING),
          pytest.raises(BudgetLedgerError) as caught):
        getattr(settlement, operation)(*args, graph.memory_log, graph.reflector, {})

    assert caught.value.reason_code == "BUDGET_LEDGER_WRITE_FAILED"
    assert len(writes) == 2
    assert model.calls == []
    assert mature_returns == [("AAPL", "2026-01-05")]
    assert len(graph.memory_log.get_pending_entries()) == 3
    assert "Reflection failed" not in caplog.text
    assert tracker.snapshot().usage_complete is False
    assert "BUDGET_LEDGER_WRITE_FAILED" in tracker.snapshot().reason_codes


@pytest.mark.unit
def test_fr002_standalone_ledger_error_writes_separate_failed_record_and_keeps_entries_pending(
        tmp_path, mature_returns):
    """REQ-TA-FR-002/QR-004: an accounting failure stays unknown in its own persisted record."""
    graph = _graph(tmp_path, UsageModel())
    graph.memory_log.store_decision("AAPL", "2026-01-05", "Rating: Buy")
    calls = []

    class BrokenAccounting:
        def reflect_on_final_decision(self, **kwargs):
            calls.append(1)
            tracker = current_run_context().tracker
            tracker.mark_history_unavailable("BUDGET_LEDGER_WRITE_FAILED")
            raise BudgetLedgerError("BUDGET_LEDGER_WRITE_FAILED")

    graph.reflector = BrokenAccounting()
    with pytest.raises(BudgetLedgerError):
        graph.settle_pending("AAPL")

    records = list((tmp_path / "results" / "settlements").glob("*.json"))
    assert len(records) == 1
    persisted = json.loads(records[0].read_text(encoding="utf-8"))
    assert persisted == graph.last_settlement_record
    assert persisted["replayable_settings"] == {"operation": "settlement", "token_budget": 100}
    metadata = persisted["run_metadata"]
    assert metadata["status"] == "failed"
    assert metadata["total_tokens"] is None
    assert metadata["usage_complete"] is False
    assert metadata["budget"]["known_tokens"] is None
    assert "BUDGET_LEDGER_WRITE_FAILED" in metadata["budget"]["reason_codes"]
    assert calls == [1]
    assert len(graph.memory_log.get_pending_entries()) == 1
    assert current_run_context() is None


@pytest.mark.unit
def test_fr002_standalone_provider_failure_writes_failed_record_without_changing_analysis_usage(
        tmp_path, mature_returns):
    """REQ-TA-FR-002/QR-001/QR-004: a handled provider failure is failed in the separate operation."""
    observer = UsageCallbackHandler()
    model = UsageModel(callbacks=[observer], fail_at=1)
    graph = _graph(tmp_path, model, limit=None)
    with graph.observation_scope() as analysis_tracker:
        analysis_tracker.start_call("analysis", "analyst.market")
        analysis_tracker.finish_call("analysis", UsageObservation(7, 1, 8, "complete"))
    analysis_record = graph.run_settings()
    graph.memory_log.store_decision("AAPL", "2026-01-05", "Rating: Buy")
    graph.memory_log.store_decision("AAPL", "2026-01-12", "Rating: Buy")

    result = graph.settle_pending("AAPL")

    assert len(result.failed) == 1
    assert result.settled == [("AAPL", "2026-01-12")]
    assert len(model.calls) == 2
    assert graph.run_settings() == analysis_record
    assert analysis_tracker.snapshot().total_tokens == 8
    records = list((tmp_path / "results" / "settlements").glob("*.json"))
    assert len(records) == 1
    metadata = json.loads(records[0].read_text(encoding="utf-8"))["run_metadata"]
    assert metadata["status"] == "failed"
    assert metadata["usage_complete"] is False
    assert metadata["total_tokens"] is None
    assert metadata["budget"]["known_tokens"] == 5
    assert metadata["budget"]["usage_state"] == "partial"
    assert metadata["budget"]["reason_codes"] == ["NOT_CONFIGURED"]
    assert current_run_context() is None
