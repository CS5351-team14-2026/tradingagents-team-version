"""Recorded usage and atomic budget policy (REQ-TA-FR-002; REQ-TA-QR-004/005).

These deterministic tests exercise the S1 foundation, not graph enforcement.
No provider, data vendor, file-backed ledger, or network access is required.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import FrozenInstanceError

import pytest

from tradingagents.run_budget import (
    BUDGET_EXHAUSTED,
    BUDGET_OK,
    BUDGET_WARNING,
    CallRole,
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
    current_run_context,
)


def _complete(tokens_in, tokens_out):
    return UsageObservation(tokens_in, tokens_out, state="complete", source="usage_metadata")


@pytest.mark.unit
@pytest.mark.parametrize("value", [-1, True, False, 1.5, "10"])
def test_req_ta_fr_002_rejects_invalid_budgets(value):
    """REQ-TA-FR-002 D6: a budget is a non-negative integer or disabled."""
    with pytest.raises(ValueError, match="token budget"):
        RunBudgetTracker(value)


@pytest.mark.unit
@pytest.mark.parametrize("used, expected", [(9, BUDGET_OK), (10, BUDGET_EXHAUSTED), (11, BUDGET_EXHAUSTED)])
def test_req_ta_fr_002_recorded_boundary_controls_only_subsequent_optional_calls(used, expected):
    """REQ-TA-FR-002: < N permits, == N and > N block subsequent optional calls."""
    tracker = RunBudgetTracker(10)
    assert tracker.try_start(call_id="first", phase="research", role=CallRole.OPTIONAL).allowed
    tracker.finish_call("first", _complete(used, 0))
    snapshot = tracker.snapshot()
    assert snapshot.status == expected
    assert snapshot.known_tokens == used
    next_call = tracker.try_start(call_id="next", phase="risk", role=CallRole.OPTIONAL)
    assert next_call.allowed is (used < 10)
    assert tracker.snapshot().llm_calls == (2 if used < 10 else 1)
    assert snapshot.reason_codes == ({
        9: ("WITHIN_RECORDED_BUDGET",),
        10: ("RECORDED_USAGE_REACHED_LIMIT",),
        11: ("RECORDED_USAGE_EXCEEDED_LIMIT",),
    }[used])


@pytest.mark.unit
def test_req_ta_fr_002_zero_budget_blocks_optional_without_fabricating_observed_zero():
    """REQ-TA-FR-002 D6: zero prevents optional work but does not invent usage."""
    tracker = RunBudgetTracker(0)
    assert not tracker.try_start(call_id="research", phase="research", role=CallRole.OPTIONAL).allowed
    snapshot = tracker.snapshot()
    assert snapshot.status == BUDGET_EXHAUSTED
    assert snapshot.reason_codes == ("ZERO_TOKEN_BUDGET",)
    assert snapshot.known_tokens is None
    assert snapshot.total_tokens is None
    assert snapshot.llm_calls == 0
    assert snapshot.blocked_calls == 1


@pytest.mark.unit
def test_req_ta_fr_002_zero_budget_reason_does_not_invent_usage_for_required_call():
    """REQ-TA-FR-002: an unreported required call cannot imply a recorded zero."""
    tracker = RunBudgetTracker(0)
    assert tracker.try_start(call_id="final", phase="final", role=CallRole.REQUIRED).allowed
    assert tracker.snapshot().reason_codes == ("ZERO_TOKEN_BUDGET",)
    tracker.finish_call("final", UsageObservation())
    snapshot = tracker.snapshot()
    assert snapshot.status == BUDGET_EXHAUSTED
    assert snapshot.reason_codes == ("ZERO_TOKEN_BUDGET",)
    assert snapshot.known_tokens is None


@pytest.mark.unit
def test_req_ta_fr_002_inflight_call_can_exceed_limit_and_required_call_remains_allowed():
    """REQ-TA-FR-002 D4/5: admission is not a hard cap or cancellation mechanism."""
    tracker = RunBudgetTracker(5)
    assert tracker.try_start(call_id="research", phase="research", role=CallRole.OPTIONAL).allowed
    tracker.finish_call("research", _complete(8, 4))
    assert tracker.snapshot().known_tokens == 12
    assert not tracker.try_start(call_id="risk", phase="risk", role=CallRole.OPTIONAL).allowed
    assert tracker.try_start(call_id="final", phase="final", role=CallRole.REQUIRED).allowed
    tracker.finish_call("final", _complete(2, 1))
    assert tracker.snapshot().known_tokens == 15
    assert tracker.snapshot().status == BUDGET_EXHAUSTED


@pytest.mark.unit
def test_req_ta_fr_002_initial_missing_and_real_zero_are_distinct():
    """REQ-TA-FR-002 / QR-004: no provider report is unavailable, never zero."""
    tracker = RunBudgetTracker(10)
    initial = tracker.snapshot()
    assert initial.known_tokens is None
    assert initial.tokens_in is None and initial.tokens_out is None
    assert initial.total_tokens is None and not initial.usage_complete
    tracker.start_call("actual-zero")
    tracker.finish_call("actual-zero", _complete(0, 0))
    complete = tracker.snapshot()
    assert complete.known_tokens == complete.total_tokens == 0
    assert complete.usage_complete
    assert complete.status == BUDGET_OK
    tracker.start_call("missing")
    tracker.finish_call("missing", UsageObservation())
    missing = tracker.snapshot()
    assert missing.known_tokens == 0  # only the first call's actual report
    assert missing.total_tokens is None and not missing.usage_complete
    assert missing.usage_state == "partial"
    assert missing.status == BUDGET_WARNING
    assert not tracker.try_start(call_id="later", phase="risk", role=CallRole.OPTIONAL).allowed


@pytest.mark.unit
@pytest.mark.parametrize("observation", [
    UsageObservation(tokens_in=10, state="partial"),
    UsageObservation(tokens_out=10, state="partial"),
    UsageObservation(total_tokens=10, state="partial"),
    UsageObservation(tokens_in=6, tokens_out=4, state="partial"),
])
def test_req_ta_fr_002_partial_reported_lower_bound_can_exhaust_budget(observation):
    """REQ-TA-FR-002 D1: recorded components can prove >= N without a full total."""
    tracker = RunBudgetTracker(10)
    tracker.finish_call("partial", observation)
    snapshot = tracker.snapshot()
    assert snapshot.known_tokens == 10
    assert snapshot.total_tokens is None
    assert not snapshot.usage_complete
    assert snapshot.status == BUDGET_EXHAUSTED
    assert not tracker.try_start(call_id="next", phase="risk", role=CallRole.OPTIONAL).allowed


@pytest.mark.unit
@pytest.mark.parametrize("observation, reason", [
    (UsageObservation(), "USAGE_UNAVAILABLE"),
    (UsageObservation(tokens_in=2, state="partial"), "USAGE_PARTIAL"),
    (UsageObservation(tokens_in=2, state="conflict"), "USAGE_CONFLICT"),
])
def test_req_ta_fr_002_unknown_usage_warns_and_conservatively_blocks_optional(observation, reason):
    """REQ-TA-FR-002 D1/2/3: WARNING is uncertainty, not an invented numeric threshold."""
    tracker = RunBudgetTracker(10)
    tracker.finish_call("uncertain", observation)
    snapshot = tracker.snapshot()
    assert snapshot.status == BUDGET_WARNING
    assert snapshot.reason_codes == (reason,)
    assert snapshot.total_tokens is None
    assert not tracker.try_start(call_id="next", phase="risk", role=CallRole.OPTIONAL).allowed


@pytest.mark.unit
def test_req_ta_fr_002_disabled_budget_keeps_observation_without_blocking_optional():
    """REQ-TA-FR-002 D7: disabled policy never changes the existing call sequence."""
    tracker = RunBudgetTracker()
    tracker.finish_call("unknown", UsageObservation())
    assert tracker.try_start(call_id="optional", phase="risk", role=CallRole.OPTIONAL).allowed
    snapshot = tracker.snapshot()
    assert snapshot.status == BUDGET_OK
    assert snapshot.reason_codes == ("NOT_CONFIGURED",)
    assert snapshot.total_tokens is None


@pytest.mark.unit
def test_req_ta_fr_002_duplicate_callbacks_and_richer_usage_update_one_call():
    """REQ-TA-FR-002: repeated constructor/config callbacks do not double usage."""
    tracker = RunBudgetTracker(100)
    tracker.start_call("same")
    tracker.start_call("same")
    tracker.finish_call("same", UsageObservation())
    tracker.finish_call("same", UsageObservation(tokens_in=4, state="partial"))
    tracker.finish_call("same", _complete(4, 6))
    tracker.finish_call("same", _complete(4, 6))
    tracker.finish_call("same", UsageObservation())
    tracker.fail_call("same")
    tracker.record_tool("tool")
    tracker.record_tool("tool")
    snapshot = tracker.snapshot()
    assert snapshot.llm_calls == snapshot.tool_calls == 1
    assert snapshot.total_tokens == snapshot.known_tokens == 10
    assert snapshot.usage_complete
    assert snapshot.pending_calls == 0


@pytest.mark.unit
def test_req_ta_fr_002_conflicting_duplicate_is_unknown_and_cannot_reopen_exhausted_gate():
    """REQ-TA-FR-002: conflicting late reports cannot silently lower or reopen a limit."""
    tracker = RunBudgetTracker(10)
    tracker.finish_call("same", _complete(10, 0))
    tracker.finish_call("same", _complete(5, 0))
    snapshot = tracker.snapshot()
    assert snapshot.usage_state == "conflict"
    assert snapshot.known_tokens is None
    assert not snapshot.usage_complete
    assert snapshot.status == BUDGET_EXHAUSTED
    assert not tracker.try_start(call_id="next", phase="risk", role=CallRole.OPTIONAL).allowed


@pytest.mark.unit
def test_req_ta_fr_002_partial_batch_floor_upgrades_without_double_count_or_false_conflict():
    """REQ-TA-FR-002: richer batched usage may fill previously unreported groups."""
    tracker = RunBudgetTracker(20)
    floor = UsageObservation(6, 2, 8, state="partial", source="generations_lower_bound")
    tracker.finish_call("batch", floor)
    assert tracker.snapshot().known_tokens == 8
    tracker.finish_call("batch", _complete(6, 6))
    tracker.finish_call("batch", floor)
    snapshot = tracker.snapshot()
    assert snapshot.usage_complete
    assert snapshot.total_tokens == snapshot.known_tokens == 12
    assert snapshot.llm_calls == 1


@pytest.mark.unit
def test_req_ta_fr_002_exact_batch_usage_cannot_undercut_a_recorded_floor():
    """REQ-TA-FR-002: an exact report below a prior batch floor is inconsistent."""
    tracker = RunBudgetTracker(20)
    tracker.finish_call("batch", UsageObservation(
        total_tokens=12, state="partial", source="generations_lower_bound"))
    tracker.finish_call("batch", _complete(5, 5))
    assert tracker.snapshot().usage_state == "conflict"
    assert tracker.snapshot().known_tokens is None
    assert not tracker.try_start(call_id="next", phase="risk", role=CallRole.OPTIONAL).allowed


@pytest.mark.unit
@pytest.mark.parametrize("restore_before_final", [False, True])
def test_req_ta_fr_002_batch_floor_never_erases_exact_partial_total(restore_before_final):
    """REQ-TA-FR-002: exact provenance survives floors, richer callbacks and restore."""
    tracker = RunBudgetTracker(20)
    tracker.finish_call("batch", UsageObservation(
        tokens_in=3, total_tokens=3, state="partial", source="generations_lower_bound"))
    tracker.finish_call("batch", UsageObservation(
        total_tokens=5, state="partial", source="llm_output.token_usage"))
    assert tracker.snapshot().known_tokens == 5
    assert not tracker.snapshot().usage_complete
    if restore_before_final:
        tracker = RunBudgetTracker.restore(tracker.export_state())
    tracker.finish_call("batch", _complete(3, 3))
    snapshot = tracker.snapshot()
    assert snapshot.usage_state == "conflict"
    assert snapshot.known_tokens is None and snapshot.total_tokens is None
    assert not snapshot.usage_complete
    assert not tracker.try_start(call_id="next", phase="risk", role=CallRole.OPTIONAL).allowed
    # Already-conflicting facts remain unknown after another round-trip too.
    assert RunBudgetTracker.restore(tracker.export_state()).snapshot() == tracker.snapshot()


@pytest.mark.unit
def test_req_ta_fr_002_exact_provenance_accepts_a_compatible_richer_report():
    """REQ-TA-FR-002: provenance checks do not reject consistent total-only usage."""
    tracker = RunBudgetTracker(20)
    tracker.finish_call("batch", UsageObservation(
        tokens_in=3, total_tokens=3, state="partial", source="generations_lower_bound"))
    tracker.finish_call("batch", UsageObservation(
        total_tokens=5, state="partial", source="llm_output.token_usage"))
    tracker = RunBudgetTracker.restore(tracker.export_state())
    tracker.finish_call("batch", _complete(3, 2))
    assert tracker.snapshot().usage_complete
    assert tracker.snapshot().total_tokens == 5


@pytest.mark.unit
def test_req_ta_fr_002_pending_parallel_calls_can_overshoot_then_block_new_starts():
    """REQ-TA-FR-002 D5: parallel requests admitted before usage may all finish over N."""
    tracker = RunBudgetTracker(10)
    for call_id in ("market", "news", "memory"):
        assert tracker.try_start(call_id=call_id, phase=call_id, role=CallRole.OPTIONAL).allowed
    assert tracker.snapshot().pending_calls == 3
    assert tracker.snapshot().known_tokens is None

    def finish(call_id):
        for _ in range(5):
            tracker.finish_call(call_id, _complete(5, 1))

    with ThreadPoolExecutor(max_workers=3) as workers:
        list(workers.map(finish, ("market", "news", "memory")))
    snapshot = tracker.snapshot()
    assert snapshot.known_tokens == 18
    assert snapshot.llm_calls == 3 and snapshot.pending_calls == 0
    assert snapshot.status == BUDGET_EXHAUSTED
    assert not tracker.try_start(call_id="later", phase="risk", role=CallRole.OPTIONAL).allowed


@pytest.mark.unit
def test_req_ta_fr_002_repeated_admission_is_one_start_and_block_is_idempotent():
    """REQ-TA-FR-002: duplicate dispatch observations do not create phantom calls."""
    tracker = RunBudgetTracker(1)
    assert tracker.try_start(call_id="first", phase="research", role=CallRole.OPTIONAL).allowed
    duplicate = tracker.try_start(call_id="first", phase="research", role=CallRole.OPTIONAL)
    assert not duplicate.allowed
    assert duplicate.reason_codes == ("ALREADY_STARTED",)
    tracker.finish_call("first", _complete(1, 0))
    for _ in range(3):
        assert not tracker.try_start(call_id="blocked", phase="risk", role=CallRole.OPTIONAL).allowed
    assert tracker.snapshot().llm_calls == tracker.snapshot().blocked_calls == 1


@pytest.mark.unit
def test_req_ta_fr_002_export_restore_preserves_identity_usage_and_exhaustion():
    """REQ-TA-FR-002 D8: pure ledger round-trip does not reset a run's cumulative usage."""
    tracker = RunBudgetTracker(10, run_id="analysis-run")
    tracker.start_call("observed", phase="analyst")
    tracker.finish_call("observed", _complete(7, 4))
    tracker.start_call("pending", phase="reflection")
    tracker.record_tool("tool")
    assert not tracker.try_start(call_id="blocked", phase="risk", role=CallRole.OPTIONAL).allowed
    restored = RunBudgetTracker.restore(tracker.export_state())
    assert restored.snapshot() == tracker.snapshot()
    assert restored.export_state() == tracker.export_state()
    assert restored.snapshot().pending_calls == 1
    assert not restored.snapshot().usage_complete
    assert not restored.try_start(call_id="new", phase="risk", role=CallRole.OPTIONAL).allowed
    # Export is a detached value; a consumer cannot mutate the live ledger.
    detached = restored.export_state()
    detached["calls"].clear()
    assert restored.snapshot().llm_calls == 2


@pytest.mark.unit
@pytest.mark.parametrize("mutation", [
    lambda state: state.update(version=2),
    lambda state: state.update(unknown_field="not allowed"),
    lambda state: state.update(exhausted="false"),
    lambda state: state.update(limit=-1),
    lambda state: state.update(calls="invalid"),
    lambda state: state["calls"].append(dict(state["calls"][0])),
    lambda state: state["calls"][0].update(terminal="yes"),
    lambda state: state["calls"][0]["usage"].update(tokens_in=True),
    lambda state: state["calls"][0]["usage"].update(extra="not allowed"),
    lambda state: state["calls"][0].update(exact_usage=None),
    lambda state: state["calls"][0]["exact_usage"].update(extra="not allowed"),
    lambda state: state["calls"][0]["exact_usage"].update(source="generations_lower_bound"),
    lambda state: state["calls"][0].update(terminal=False),
    lambda state: state["calls"][0].update(exact_usage={
        "tokens_in": None, "tokens_out": None, "total_tokens": 4,
        "state": "partial", "source": "llm_output.token_usage",
    }),
])
def test_req_ta_fr_002_corrupt_ledger_is_rejected_instead_of_reset(mutation):
    """REQ-TA-FR-002 D8: invalid saved usage cannot silently become a zero-count run."""
    tracker = RunBudgetTracker(10)
    tracker.finish_call("call", _complete(1, 2))
    state = tracker.export_state()
    mutation(state)
    with pytest.raises(ValueError):
        RunBudgetTracker.restore(state)


@pytest.mark.unit
@pytest.mark.parametrize("kwargs", [
    {"tokens_in": -1, "state": "partial"},
    {"tokens_out": True, "state": "partial"},
    {"total_tokens": 1.5, "state": "partial"},
    {"tokens_in": 0, "state": "unavailable"},
    {"tokens_in": 1, "state": "complete"},
    {"tokens_in": 1, "tokens_out": 2, "total_tokens": 9, "state": "complete"},
    {"tokens_in": 4, "total_tokens": 3, "state": "partial"},
    {"state": "estimated"},
    {"state": []},
])
def test_req_ta_fr_002_usage_observation_rejects_estimates_and_invalid_counts(kwargs):
    """REQ-TA-FR-002: malformed counts must be diagnosed by the normalizer, not trusted."""
    with pytest.raises(ValueError):
        UsageObservation(**kwargs)


@pytest.mark.unit
def test_req_ta_fr_002_contexts_isolate_runs_and_restore_after_failure():
    """REQ-TA-FR-002 / QR-003: workers share an explicit run, later runs get a fresh one."""
    assert current_run_context() is None
    first = RunBudgetContext(RunBudgetTracker())
    second = RunBudgetContext(RunBudgetTracker())
    with first.activate():
        assert current_run_context() is first
        worker_context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as worker:
            assert worker.submit(worker_context.run, current_run_context).result() is first
        with pytest.raises(RuntimeError), second.activate():
            assert current_run_context() is second
            raise RuntimeError("controlled fixture failure")
        assert current_run_context() is first
    assert current_run_context() is None
    assert first.tracker.run_id != second.tracker.run_id


@pytest.mark.unit
def test_req_ta_qr_004_snapshot_is_immutable_and_stats_mark_incomplete_usage():
    """REQ-TA-QR-004: consumers cannot mutate the accounting source through snapshots."""
    tracker = RunBudgetTracker()
    tracker.finish_call("partial", UsageObservation(tokens_in=3, state="partial"))
    snapshot = tracker.snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.tokens_in = 100
    stats = snapshot.to_stats()
    assert stats["tokens_in"] == 3
    assert stats["tokens_out"] is None
    assert stats["total_tokens"] is None
    assert stats["usage_complete"] is False
    assert stats["usage_state"] == "partial"
    stats["tokens_in"] = 100
    assert tracker.snapshot().tokens_in == 3
