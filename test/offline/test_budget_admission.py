"""Admission at the invocation boundary (REQ-TA-FR-002; ADR-004).

Offline tests of ``llm_clients.invocation``: an OPTIONAL call is refused once
the budget stops it, a REQUIRED call is always admitted, no context means
admitted (baseline), and a refusal carries machine-readable reasons and never
becomes a provider error.
"""

from __future__ import annotations

import pytest

from tradingagents.llm_clients.invocation import (
    BudgetInvocationRefused,
    admit_optional,
    require_or_admit,
)
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
def test_no_context_admits_everything():
    """REQ-TA-FR-002 (D6): with no budget context, calls are admitted (baseline)."""
    assert admit_optional("debate").allowed is True


@pytest.mark.unit
def test_optional_refused_when_exhausted():
    """REQ-TA-FR-002 (D4): an optional call is refused once usage reaches N."""
    with RunBudgetContext(_exhausted()).activate():
        admission = admit_optional("debate")
    assert admission.allowed is False
    assert admission.reason_codes


@pytest.mark.unit
def test_optional_admitted_below_budget():
    """REQ-TA-FR-002: an optional call is admitted while usage is complete and below N."""
    t = RunBudgetTracker(1000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(10, 5, USAGE_COMPLETE))
    with RunBudgetContext(t).activate():
        assert admit_optional("debate").allowed is True


@pytest.mark.unit
def test_required_always_admitted():
    """REQ-TA-FR-002 (D4): a required call is admitted even at the limit."""
    with RunBudgetContext(_exhausted()).activate():
        admission = require_or_admit("synthesis", role=CallRole.REQUIRED, call_id="final")
    assert admission.allowed is True


@pytest.mark.unit
def test_zero_budget_refuses_optional_immediately():
    """REQ-TA-FR-002 (D6): a zero budget refuses optional calls at once."""
    with RunBudgetContext(RunBudgetTracker(0)).activate():
        assert admit_optional("debate").allowed is False


@pytest.mark.unit
def test_refusal_is_not_a_provider_error():
    """REQ-TA-FR-002: refusal is a distinct control result with reason codes, not an LLM error."""
    refusal = BudgetInvocationRefused("debate", ("RECORDED_USAGE_REACHED_LIMIT",))
    assert refusal.phase == "debate"
    assert refusal.reason_codes == ("RECORDED_USAGE_REACHED_LIMIT",)
    assert not isinstance(refusal, ConnectionError)
