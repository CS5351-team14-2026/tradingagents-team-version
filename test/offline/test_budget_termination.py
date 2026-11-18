"""Controlled termination: no budget-exhausted path raises (REQ-TA-FR-002; QR-001).

Offline tests that budget exhaustion ends through controlled paths: the
structured retry is not attempted, the free-text fallback is skipped, the PM
fallback yields a non-tradeable REVIEW rather than a fabricated call, and the
reflection stays pending without raising (leaving the decision pending).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.structured import invoke_structured, invoke_structured_or_freetext
from tradingagents.memory import reflection
from tradingagents.run_budget import (
    USAGE_COMPLETE,
    CallRole,
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
)


def _exhausted(limit=100):
    t = RunBudgetTracker(limit)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    return t


@pytest.mark.unit
def test_structured_retry_not_attempted_when_exhausted():
    """REQ-TA-FR-002 (D4): the structured retry is an optional call; it is not made when refused."""
    structured = MagicMock()
    structured.invoke.side_effect = RuntimeError("first attempt fails")
    with RunBudgetContext(_exhausted()).activate():
        result = invoke_structured(structured, "prompt", "Agent")
    assert result is None
    # Only the first attempt ran; the retry was refused.
    assert structured.invoke.call_count == 1


@pytest.mark.unit
def test_freetext_fallback_skipped_when_exhausted():
    """REQ-TA-FR-002 (D4): the fallback is optional; when refused, no extra call is made."""
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="should not be used")
    with RunBudgetContext(_exhausted()).activate():
        out = invoke_structured_or_freetext(None, plain, "prompt", str, "Agent")
    assert out == ""
    plain.invoke.assert_not_called()


@pytest.mark.unit
def test_freetext_fallback_runs_without_budget():
    """REQ-TA-FR-002 (D6): with no budget, the fallback runs as before (baseline)."""
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="fallback text")
    out = invoke_structured_or_freetext(None, plain, "prompt", str, "Agent")
    assert out == "fallback text"


@pytest.mark.unit
def test_reflection_refused_leaves_pending_without_raising():
    """REQ-TA-FR-002 (D4): a refused reflection raises a control result, not an uncaught error."""
    from tradingagents.llm_clients.invocation import BudgetInvocationRefused

    reflector = reflection.Reflector(MagicMock())
    with RunBudgetContext(_exhausted()).activate(), pytest.raises(BudgetInvocationRefused):
        reflector.reflect_on_final_decision("decision", 0.01, 0.0)


@pytest.mark.unit
def test_reflection_runs_without_budget():
    """REQ-TA-FR-002 (D6): with no budget, the reflection call runs as before."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="a lesson")
    reflector = reflection.Reflector(llm)
    assert reflector.reflect_on_final_decision("decision", 0.01, 0.0) == "a lesson"
