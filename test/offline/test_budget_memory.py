"""Budgeted reflection and durable settlement (REQ-TA-FR-002/QR-001/QR-005)."""

from __future__ import annotations

import logging
import threading

import pytest

from tradingagents.llm_clients.invocation import BudgetInvocationRefused
from tradingagents.memory import TradingMemoryLog, settlement
from tradingagents.memory.reflection import Reflector
from tradingagents.run_budget import RunBudgetContext, RunBudgetTracker, UsageObservation

from .test_budget_entrypoints import UsageModel


def _log(tmp_path, entries):
    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "memory.md")})
    for ticker, date in entries:
        log.store_decision(ticker, date, "Rating: Buy\nA recorded decision.")
    return log


@pytest.fixture
def mature_returns(monkeypatch):
    """Keep settlement deterministic; the suite's network block remains active."""
    calls = []

    def fetch(ticker, date, holding_days=5, benchmark="SPY"):
        calls.append((ticker, date))
        return 0.05, 0.02, holding_days, "2026-02-02"

    monkeypatch.setattr(settlement, "fetch_returns", fetch)
    return calls


@pytest.mark.unit
@pytest.mark.parametrize("recorded", [5, 6], ids=["exact-limit", "over-limit"])
def test_fr002_reflection_is_optional_after_recorded_limit(recorded):
    """REQ-TA-FR-002: a reflection cannot start at or above N."""
    tracker = RunBudgetTracker(limit=5)
    tracker.start_call("earlier", "analysis")
    tracker.finish_call("earlier", UsageObservation(recorded, 0, recorded, "complete"))
    model = UsageModel()

    with RunBudgetContext(tracker).activate(), pytest.raises(BudgetInvocationRefused) as refused:
        Reflector(model).reflect_on_final_decision("Rating: Buy", 0.05, 0.02)

    assert refused.value.phase == "reflection"
    assert model.calls == []
    assert tracker.snapshot().blocked_calls == 1
    assert tracker.snapshot().known_tokens == recorded


@pytest.mark.unit
def test_fr002_started_reflection_can_exceed_limit_and_blocks_the_next_one():
    """REQ-TA-FR-002: recorded usage gates later work without claiming a hard cap."""
    tracker = RunBudgetTracker(limit=4)
    model = UsageModel()
    reflector = Reflector(model)

    with RunBudgetContext(tracker).activate():
        assert reflector.reflect_on_final_decision("Rating: Buy", 0.05, 0.02)
        with pytest.raises(BudgetInvocationRefused):
            reflector.reflect_on_final_decision("Rating: Buy", 0.05, 0.02)

    assert len(model.calls) == 1
    assert tracker.snapshot().known_tokens == 5
    assert tracker.snapshot().status == "BUDGET_EXHAUSTED"


@pytest.mark.unit
@pytest.mark.parametrize("mode,known", [("partial", 3), ("unavailable", None)])
def test_fr002_incomplete_reflection_usage_is_not_a_complete_zero(mode, known):
    """REQ-TA-FR-002/QR-004: incomplete usage keeps known facts and blocks more optional work."""
    tracker = RunBudgetTracker(limit=100)
    model = UsageModel(usage_mode=mode)
    reflector = Reflector(model)

    with RunBudgetContext(tracker).activate():
        reflector.reflect_on_final_decision("Rating: Buy", 0.05, 0.02)
        with pytest.raises(BudgetInvocationRefused):
            reflector.reflect_on_final_decision("Rating: Buy", 0.05, 0.02)

    snapshot = tracker.snapshot()
    assert len(model.calls) == 1
    assert snapshot.known_tokens == known
    assert snapshot.total_tokens is None
    assert snapshot.usage_state == mode
    assert snapshot.usage_complete is False
    assert snapshot.status == "BUDGET_WARNING"


@pytest.mark.unit
@pytest.mark.parametrize("all_tickers", [False, True], ids=["one-ticker", "all-tickers"])
def test_fr002_budget_refusal_leaves_pending_without_attempting_remaining_reflections(
        tmp_path, mature_returns, caplog, all_tickers):
    """REQ-TA-FR-002/QR-001: budget refusal ends settlement without provider-failure diagnostics."""
    entries = [("AAPL", "2026-01-05"), ("AAPL", "2026-01-12"), ("MSFT", "2026-01-05")]
    log = _log(tmp_path, entries)
    tracker = RunBudgetTracker(limit=0)
    model = UsageModel()
    with RunBudgetContext(tracker).activate(), caplog.at_level(logging.INFO):
        if all_tickers:
            result = settlement.settle_all_pending(log, Reflector(model), {})
        else:
            result = settlement.settle_pending("AAPL", log, Reflector(model), {})

    assert result.settled == result.failed == []
    assert len(result.budget_skipped) == 1
    assert result.budget_skipped[0][:2] == entries[0]
    assert result.budget_skipped[0][2] == ("ZERO_TOKEN_BUDGET",)
    assert model.calls == []
    assert tracker.snapshot().blocked_calls == 1
    assert mature_returns == [entries[0]]
    assert len(log.get_pending_entries()) == len(entries)
    assert "Reflection failed" not in caplog.text


@pytest.mark.unit
def test_fr002_settlement_keeps_finished_outcomes_when_later_reflection_is_refused(
        tmp_path, mature_returns):
    """REQ-TA-FR-002/INV-002: completed lessons stay durable; skipped entries retry once later."""
    entries = [("AAPL", "2026-01-05"), ("AAPL", "2026-01-12"), ("AAPL", "2026-01-19")]
    log = _log(tmp_path, entries)
    model = UsageModel()
    with RunBudgetContext(RunBudgetTracker(limit=5)).activate():
        first = settlement.settle_pending("AAPL", log, Reflector(model), {})

    reopened = TradingMemoryLog({"memory_log_path": str(tmp_path / "memory.md")})
    assert first.settled == entries[:1]
    assert first.failed == []
    assert [entry["date"] for entry in reopened.get_pending_entries()] == [date for _, date in entries[1:]]
    assert reopened.load_entries()[0]["reflection"]

    with RunBudgetContext(RunBudgetTracker()).activate():
        resumed = settlement.settle_pending("AAPL", reopened, Reflector(model), {})
        again = settlement.settle_pending("AAPL", reopened, Reflector(model), {})

    assert resumed.settled == entries[1:]
    assert resumed.failed == resumed.budget_skipped == []
    assert again.settled == again.failed == again.budget_skipped == []
    assert len(model.calls) == len(entries)
    assert reopened.get_pending_entries() == []


@pytest.mark.unit
def test_fr002_no_budget_keeps_provider_failure_nonblocking_and_pending(tmp_path, mature_returns):
    """REQ-TA-FR-002/QR-001: disabling budget retains existing nonblocking provider failures."""
    entries = [("AAPL", "2026-01-05"), ("AAPL", "2026-01-12")]
    log = _log(tmp_path, entries)
    model = UsageModel(fail_at=1)
    with RunBudgetContext(RunBudgetTracker()).activate():
        result = settlement.settle_pending("AAPL", log, Reflector(model), {})

    assert len(model.calls) == 2
    assert result.settled == entries[1:]
    assert len(result.failed) == 1
    assert "reflection failed: provider unavailable" in result.failed[0][2]
    assert result.budget_skipped == []
    assert [entry["date"] for entry in log.get_pending_entries()] == [entries[0][1]]


@pytest.mark.unit
def test_fr002_budgeted_settlement_still_honours_nonblocking_log_lock(tmp_path, mature_returns):
    """REQ-TA-FR-002/QR-005: a busy log does not start a reflection or wait for the lock."""
    entries = [("AAPL", "2026-01-05")]
    log = _log(tmp_path, entries)
    held, release = threading.Event(), threading.Event()

    def hold_log():
        with log.settling():
            held.set()
            assert release.wait(5)

    worker = threading.Thread(target=hold_log)
    worker.start()
    model = UsageModel()
    try:
        assert held.wait(5)
        with RunBudgetContext(RunBudgetTracker(limit=5)).activate():
            result = settlement.settle_all_pending(log, Reflector(model), {}, wait=False)
        assert result.settled == result.failed == result.budget_skipped == []
        assert model.calls == []
        assert mature_returns == []
        assert len(log.get_pending_entries()) == 1
    finally:
        release.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
