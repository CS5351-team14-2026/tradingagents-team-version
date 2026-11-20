"""Concurrency and in-flight overshoot semantics (REQ-TA-FR-002; ADR-004 D5).

Offline tests that the shared ledger is safe under parallel updates, that a
single in-flight call may push recorded usage past the limit (no exact hard-cap
claim), that duplicate callback delivery does not double-count, and that a late
event charges the run that started the call.
"""

from __future__ import annotations

import threading

import pytest

from tradingagents.run_budget import (
    BUDGET_EXHAUSTED,
    USAGE_COMPLETE,
    CallRole,
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
)


@pytest.mark.unit
def test_parallel_updates_are_not_lost():
    """REQ-TA-FR-002 (D5): concurrent finish_call updates all count, none is lost."""
    t = RunBudgetTracker(10_000)

    def worker(i):
        t.start_call(f"c{i}", role=CallRole.REQUIRED, phase="analyst")
        t.finish_call(f"c{i}", UsageObservation(10, 5, USAGE_COMPLETE))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    snap = t.snapshot()
    assert snap.llm_calls == 50
    assert snap.tokens_in == 500
    assert snap.tokens_out == 250


@pytest.mark.unit
def test_in_flight_call_may_overshoot_limit():
    """REQ-TA-FR-002 (D5): usage above N is recorded, not clamped (no hard cap)."""
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    # Already below the limit when it started; the result pushes it over.
    t.finish_call("a", UsageObservation(90, 40, USAGE_COMPLETE))
    snap = t.snapshot()
    assert snap.known_tokens == 130
    assert snap.status == BUDGET_EXHAUSTED


@pytest.mark.unit
def test_parallel_optional_admissions_do_not_all_slip_past():
    """REQ-TA-FR-002 (D5): admission is atomic; once exhausted, optionals are refused."""
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    results = []

    def try_optional(i):
        with RunBudgetContext(t).activate():
            from tradingagents.llm_clients.invocation import admit_optional

            results.append(admit_optional("debate").allowed)

    threads = [threading.Thread(target=try_optional, args=(i,)) for i in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results and not any(results)


@pytest.mark.unit
def test_duplicate_delivery_replaces_not_adds():
    """REQ-TA-FR-002 (D5): a callback delivered twice for one call is not counted twice."""
    t = RunBudgetTracker(10_000)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(10, 5, USAGE_COMPLETE))
    t.finish_call("a", UsageObservation(10, 5, USAGE_COMPLETE))
    snap = t.snapshot()
    assert snap.tokens_in == 10 and snap.tokens_out == 5
    assert snap.llm_calls == 1


@pytest.mark.unit
def test_late_event_charges_owner_run():
    """REQ-TA-FR-002 (D5): a late end event belongs to the run that started the call."""
    t1 = RunBudgetTracker(10_000)
    t2 = RunBudgetTracker(10_000)
    # Run 1 starts a call.
    t1.start_call("shared", role=CallRole.REQUIRED, phase="x")
    # Its result arrives after run 2 is active: it must charge run 1, not run 2.
    with RunBudgetContext(t2).activate():
        t1.finish_call("shared", UsageObservation(10, 5, USAGE_COMPLETE))
    assert t1.snapshot().tokens_in == 10
    assert t2.snapshot().llm_calls == 0
