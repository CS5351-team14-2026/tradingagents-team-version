"""Settlement under budget refusal (REQ-TA-FR-002; ADR-004 D4/D9).

Offline tests that a budget-refused reflection is a control result: the decision
stays pending, is recorded as ``budget_skipped`` (not ``failed``), and an
all-ticker pass stops before starting another ticker once refused.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.llm_clients.invocation import BudgetInvocationRefused
from tradingagents.memory import settlement
from tradingagents.run_budget import (
    USAGE_COMPLETE,
    CallRole,
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
)


class _Log:
    def __init__(self, pending):
        self._pending = pending
        self.updated = []

    def settling(self, wait=True):
        import contextlib

        return contextlib.nullcontext(True)

    def get_pending_entries(self):
        return list(self._pending)

    def update_with_outcome(self, *a, **k):
        self.updated.append(a)
        return True


def _exhausted():
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    return t


@pytest.fixture
def priced(monkeypatch):
    closes = pd.Series([100.0 + i for i in range(12)], index=pd.bdate_range("2026-01-02", periods=12))
    monkeypatch.setattr(settlement, "get_closes", lambda *a, **k: closes)
    monkeypatch.setattr(settlement, "resolve_benchmark", lambda t, c: "SPY")


@pytest.mark.unit
def test_budget_refused_reflection_is_skipped_not_failed(priced):
    """REQ-TA-FR-002 (D4/D9): a refused reflection leaves the entry pending, never 'failed'."""
    log = _Log([{"ticker": "NVDA", "date": "2025-12-31", "decision": "Rating: Buy"}])
    reflector = MagicMock()
    reflector.reflect_on_final_decision.side_effect = BudgetInvocationRefused("reflection", ("RECORDED_USAGE_REACHED_LIMIT",))
    with RunBudgetContext(_exhausted()).activate():
        result = settlement.settle_pending("NVDA", log, reflector, {"holding_period_days": 5})
    assert result.settled == []
    assert result.failed == []
    assert result.budget_skipped and result.budget_skipped[0][0] == "NVDA"
    assert log.updated == []


@pytest.mark.unit
def test_all_pending_stops_after_budget_skip(monkeypatch):
    """REQ-TA-FR-002 (D4): an all-ticker pass stops once a reflection is refused."""
    log = _Log([
        {"ticker": "AAA", "date": "2025-12-31", "decision": "Rating: Buy"},
        {"ticker": "BBB", "date": "2025-12-31", "decision": "Rating: Buy"},
    ])
    reflector = MagicMock()

    def refuse(ticker, memory_log, reflect, config, wait=True):
        res = settlement.Settlement()
        res.budget_skipped.append((ticker, "2025-12-31", ("RECORDED_USAGE_REACHED_LIMIT",)))
        return res

    monkeypatch.setattr(settlement, "settle_pending", refuse)
    result = settlement.settle_all_pending(log, reflector, {})
    assert len(result.budget_skipped) == 1   # stopped after the first ticker
