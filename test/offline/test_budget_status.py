"""Budget status and machine-readable reasons at the boundary (REQ-TA-FR-002; ADR-004).

Offline, deterministic tests of ``RunBudgetTracker``: the three statuses,
their reason codes, D1/D2/D3 precedence, and that admission refuses optional
calls once accounting stops them while required calls still run. No numeric
warning threshold or reserve percentage is asserted (both TBD).
"""

from __future__ import annotations

import pytest

from tradingagents.run_budget import (
    BUDGET_EXHAUSTED,
    BUDGET_OK,
    BUDGET_WARNING,
    USAGE_COMPLETE,
    USAGE_PARTIAL,
    USAGE_UNAVAILABLE,
    CallRole,
    RunBudgetTracker,
    UsageObservation,
)


@pytest.mark.unit
def test_no_budget_is_ok_not_configured():
    """REQ-TA-FR-002 (D6): no budget preserves baseline; result is BUDGET_OK/NOT_CONFIGURED."""
    snap = RunBudgetTracker(None).snapshot()
    assert snap.status == BUDGET_OK
    assert "NOT_CONFIGURED" in snap.reason_codes
    assert snap.limit is None


@pytest.mark.unit
def test_usage_below_limit_is_ok_within_budget():
    """REQ-TA-FR-002: complete usage strictly below N is BUDGET_OK."""
    t = RunBudgetTracker(1000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    snap = t.snapshot()
    assert snap.status == BUDGET_OK
    assert "WITHIN_RECORDED_BUDGET" in snap.reason_codes


@pytest.mark.unit
def test_usage_reaching_limit_is_exhausted_reached():
    """REQ-TA-FR-002: recorded usage exactly at N is BUDGET_EXHAUSTED (reached)."""
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    snap = t.snapshot()
    assert snap.status == BUDGET_EXHAUSTED
    assert "RECORDED_USAGE_REACHED_LIMIT" in snap.reason_codes


@pytest.mark.unit
def test_usage_over_limit_is_exhausted_exceeded():
    """REQ-TA-FR-002 (D5): an in-flight call may push usage past N (exceeded)."""
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(90, 40, USAGE_COMPLETE))
    snap = t.snapshot()
    assert snap.status == BUDGET_EXHAUSTED
    assert "RECORDED_USAGE_EXCEEDED_LIMIT" in snap.reason_codes


@pytest.mark.unit
def test_unavailable_usage_is_warning_not_ok():
    """REQ-TA-FR-002 (D2/D3): unknown usage below N is BUDGET_WARNING, never OK as if enforced."""
    t = RunBudgetTracker(1000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(None, None, USAGE_UNAVAILABLE))
    snap = t.snapshot()
    assert snap.status == BUDGET_WARNING
    assert "USAGE_UNAVAILABLE" in snap.reason_codes
    assert snap.tokens_in is None


@pytest.mark.unit
def test_partial_usage_below_limit_is_warning():
    """REQ-TA-FR-002 (D1/D3): a partial lower bound below N is BUDGET_WARNING."""
    t = RunBudgetTracker(1000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(50, None, USAGE_PARTIAL))
    snap = t.snapshot()
    assert snap.status == BUDGET_WARNING
    assert "USAGE_PARTIAL" in snap.reason_codes
    assert snap.known_tokens == 50


@pytest.mark.unit
def test_partial_lower_bound_at_limit_is_exhausted():
    """REQ-TA-FR-002 (D1): a partial lower bound reaching N is sufficient to exhaust."""
    t = RunBudgetTracker(50)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(50, None, USAGE_PARTIAL))
    snap = t.snapshot()
    assert snap.status == BUDGET_EXHAUSTED


@pytest.mark.unit
def test_optional_refused_required_admitted_once_exhausted():
    """REQ-TA-FR-002 (D4): optional calls stop at the limit; required calls still run."""
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    refused = t.try_start(call_id="b", role=CallRole.OPTIONAL, phase="debate")
    assert refused.allowed is False
    assert refused.reason_codes
    required = t.try_start(call_id="c", role=CallRole.REQUIRED, phase="synthesis")
    assert required.allowed is True


@pytest.mark.unit
def test_optional_refused_when_usage_unavailable():
    """REQ-TA-FR-002 (D2): an unverifiable remainder conservatively blocks optional calls."""
    t = RunBudgetTracker(1000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(None, None, USAGE_UNAVAILABLE))
    assert t.try_start(call_id="b", role=CallRole.OPTIONAL, phase="d").allowed is False


@pytest.mark.unit
def test_optional_allowed_below_complete_budget():
    """REQ-TA-FR-002: complete usage below N still admits optional calls."""
    t = RunBudgetTracker(1000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(10, 5, USAGE_COMPLETE))
    assert t.try_start(call_id="b", role=CallRole.OPTIONAL, phase="d").allowed is True
