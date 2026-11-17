"""Durable cumulative budget history (REQ-TA-FR-002 D8; QR-003/004; ADR-003)."""

from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import Barrier

import pytest

from tradingagents.graph.checkpointer import BudgetLedgerStore, get_checkpointer
from tradingagents.run_budget import (
    BudgetLedgerError,
    CallRole,
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
)


def _complete():
    return UsageObservation(3, 2, 5, "complete", "usage_metadata")


def _store(tmp_path, tid="analysis-thread", ticker="NVDA"):
    return BudgetLedgerStore(tmp_path, ticker, tid)


def _loaded(tmp_path, tid="analysis-thread", ticker="NVDA"):
    state = _store(tmp_path, tid, ticker).load()
    assert state is not None
    return RunBudgetTracker.restore(state)


@pytest.mark.unit
def test_fr002_ledger_commits_every_start_usage_failure_tool_and_refusal(tmp_path):
    """REQ-TA-FR-002 D8: observations commit independently of graph snapshots."""
    store = _store(tmp_path)
    assert store.load() is None
    tracker = RunBudgetTracker(5, run_id="recorded-run")
    tracker.bind_persistence(store.save_state)
    assert _loaded(tmp_path).export_state() == tracker.export_state()

    decision = tracker.try_start(call_id="first", phase="analyst", role=CallRole.REQUIRED)
    assert decision.allowed
    assert _loaded(tmp_path).snapshot().pending_calls == 1
    tracker.finish_call("first", _complete())
    assert _loaded(tmp_path).snapshot().known_tokens == 5
    tracker.record_tool("tool-1")
    assert _loaded(tmp_path).snapshot().tool_calls == 1
    tracker.fail_call("failed-call")
    assert _loaded(tmp_path).snapshot().usage_complete is False
    decision = tracker.try_start(call_id="stopped", phase="risk", role=CallRole.OPTIONAL)
    assert not decision.allowed
    saved = _loaded(tmp_path)
    assert saved.export_state() == tracker.export_state()
    assert saved.snapshot().blocked_calls == 1


@pytest.mark.unit
def test_fr002_duplicate_and_richer_callbacks_remain_idempotent_after_durable_resume(tmp_path):
    """REQ-TA-FR-002: replacement observations do not charge the same call twice."""
    tracker = RunBudgetTracker(100)
    tracker.bind_persistence(_store(tmp_path).save_state)
    tracker.start_call("same-call", "market")
    tracker.finish_call("same-call", UsageObservation(tokens_in=3, state="partial"))
    tracker.record_tool("same-tool")

    store = _store(tmp_path)
    restored = RunBudgetTracker.restore(store.load())
    restored.bind_persistence(store.save_state)
    for _ in range(2):
        restored.start_call("same-call", "market")
        restored.finish_call("same-call", _complete())
        restored.record_tool("same-tool")
    assert _loaded(tmp_path).snapshot().llm_calls == 1
    assert _loaded(tmp_path).snapshot().tool_calls == 1
    assert _loaded(tmp_path).snapshot().known_tokens == 5
    assert _loaded(tmp_path).snapshot().usage_complete is True


@pytest.mark.unit
def test_fr002_restore_into_empty_tracker_preserves_context_reference_and_run_identity(tmp_path):
    """REQ-TA-FR-002/QR-004: CLI observers retain the same resumed tracker object."""
    before = RunBudgetTracker(100, run_id="original-analysis")
    before.finish_call("before-crash", _complete())
    before.start_call("lost-inflight", "memory.reflection")
    before.bind_persistence(_store(tmp_path).save_state)
    store = _store(tmp_path)
    saved = store.load()
    current = RunBudgetTracker(100)
    context = RunBudgetContext(current)
    current.restore_state(saved)
    assert context.tracker is current
    assert current.run_id == before.run_id
    # The pure serialization helper does not invent a crash or alter pending
    # state; only an actual durable resume resolves the lost response as unknown.
    assert RunBudgetTracker.restore(saved).snapshot().pending_calls == 1
    assert current.recover_inflight() == 1
    current.bind_persistence(store.save_state)

    snapshot = _loaded(tmp_path).snapshot()
    assert snapshot.pending_calls == 0
    assert snapshot.llm_calls == 2
    assert snapshot.known_tokens == 5
    assert snapshot.usage_complete is False and snapshot.total_tokens is None
    assert not current.try_start(call_id="optional", phase="risk", role=CallRole.OPTIONAL).allowed
    assert current.try_start(call_id="required", phase="portfolio", role=CallRole.REQUIRED).allowed
    assert current.recover_inflight() == 1


@pytest.mark.unit
def test_fr002_inflight_recovery_is_committed_when_persistence_is_already_bound(tmp_path):
    """REQ-TA-FR-002 D8: unknown pre-crash usage survives another interruption."""
    tracker = RunBudgetTracker(100)
    store = _store(tmp_path)
    tracker.bind_persistence(store.save_state)
    tracker.start_call("unknown")
    assert tracker.recover_inflight() == 1
    assert tracker.recover_inflight() == 0
    assert _loaded(tmp_path).export_state()["calls"][0]["usage"]["state"] == "unavailable"


@pytest.mark.unit
@pytest.mark.parametrize("mode,reason", [
    ("missing", "BUDGET_HISTORY_UNAVAILABLE"),
    ("bad-fields", "BUDGET_LEDGER_INVALID"),
    ("different-limit", "BUDGET_LEDGER_IDENTITY_MISMATCH"),
])
def test_fr002_unverifiable_history_latches_all_dispatch_and_never_has_complete_usage(mode, reason):
    """REQ-TA-FR-002 D8/QR-004: history cannot silently become a fresh ledger."""
    tracker = RunBudgetTracker(100)
    if mode == "missing":
        tracker.finish_call("current-observation", _complete())
        tracker.mark_history_unavailable()
    else:
        saved = RunBudgetTracker(50 if mode == "different-limit" else 100).export_state()
        if mode == "bad-fields":
            saved["unexpected"] = "forbidden"
        with pytest.raises(BudgetLedgerError) as error:
            tracker.restore_state(saved)
        assert error.value.reason_code == reason
    snapshot = tracker.snapshot()
    assert snapshot.total_tokens is None and snapshot.usage_complete is False
    assert snapshot.status == "BUDGET_WARNING" and reason in snapshot.reason_codes
    for role in CallRole:
        with pytest.raises(BudgetLedgerError) as error:
            tracker.try_start(call_id=f"next-{role}", phase="next", role=role)
        assert error.value.reason_code == reason


@pytest.mark.unit
def test_fr002_restore_into_active_or_bound_tracker_is_rejected():
    """REQ-TA-FR-002 D8: restoration cannot discard already observed work."""
    saved = RunBudgetTracker(10).export_state()
    observed = RunBudgetTracker(10)
    observed.start_call("existing")
    bound = RunBudgetTracker(10)
    bound.bind_persistence(lambda state: None)
    for tracker in (observed, bound):
        with pytest.raises(ValueError, match="empty tracker"):
            tracker.restore_state(saved)
    assert observed.snapshot().llm_calls == 1


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["bind", "start", "finish", "fail", "tool", "refuse"])
def test_fr002_persistence_failure_latches_tracker_and_surfaces_on_every_update(operation):
    """REQ-TA-FR-002/QR-004: failed commits cannot permit another LLM dispatch."""
    tracker = RunBudgetTracker(0 if operation == "refuse" else 100)
    fail = operation == "bind"

    def writer(state):
        if fail:
            raise OSError("fixture storage failure")

    if not fail:
        tracker.bind_persistence(writer)
        fail = True
    actions = {
        "bind": lambda: tracker.bind_persistence(writer),
        "start": lambda: tracker.try_start(call_id="admit", phase="market", role=CallRole.REQUIRED),
        "finish": lambda: tracker.finish_call("returned", _complete()),
        "fail": lambda: tracker.fail_call("failed"),
        "tool": lambda: tracker.record_tool("tool"),
        "refuse": lambda: tracker.try_start(call_id="optional", phase="risk", role=CallRole.OPTIONAL),
    }
    with pytest.raises(BudgetLedgerError) as error:
        actions[operation]()
    assert error.value.reason_code == "BUDGET_LEDGER_WRITE_FAILED"
    assert error.value.phase == "budget_ledger"
    assert error.value.reason_codes == ("BUDGET_LEDGER_WRITE_FAILED",)
    assert tracker.snapshot().usage_complete is False
    assert tracker.snapshot().total_tokens is None
    assert "BUDGET_LEDGER_WRITE_FAILED" in tracker.snapshot().reason_codes
    for action in (
        tracker.raise_if_unhealthy,
        lambda: tracker.start_call("later"),
        lambda: tracker.finish_call("later", _complete()),
        lambda: tracker.fail_call("later"),
        lambda: tracker.record_tool("later"),
        lambda: tracker.try_start(call_id="later", phase="portfolio", role=CallRole.REQUIRED),
        lambda: tracker.try_start(call_id="later", phase="risk", role=CallRole.OPTIONAL),
    ):
        with pytest.raises(BudgetLedgerError):
            action()


@pytest.mark.unit
def test_fr002_callback_failure_can_be_detected_after_framework_swallows_it():
    """REQ-TA-FR-002: admission/adapter checks surface swallowed callback errors."""
    saved = []

    def writer(state):
        if state["calls"] and state["calls"][0]["terminal"]:
            raise OSError("fixture commit failure")
        saved.append(copy.deepcopy(state))

    tracker = RunBudgetTracker(100)
    tracker.bind_persistence(writer)
    tracker.start_call("in-flight")
    with suppress(BudgetLedgerError):
        tracker.finish_call("in-flight", _complete())
    with pytest.raises(BudgetLedgerError):
        tracker.raise_if_unhealthy()
    assert saved[-1]["calls"][0]["terminal"] is False
    assert tracker.snapshot().known_tokens == 5
    assert tracker.snapshot().usage_complete is False


@pytest.mark.unit
def test_fr002_budget_ledger_coexists_with_graph_checkpoint_tables(tmp_path):
    """REQ-TA-FR-002 D8: graph saves cannot roll back already committed usage."""
    store = _store(tmp_path)
    tracker = RunBudgetTracker(100)
    tracker.bind_persistence(store.save_state)
    tracker.finish_call("before-graph-save", _complete())
    with get_checkpointer(tmp_path, "NVDA") as saver:
        config = {"configurable": {"thread_id": "different-graph-thread"}}
        assert saver.get_tuple(config) is None
        tables = {row[0] for row in saver.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"checkpoints", "writes", "budget_ledgers"} <= tables
        tracker.start_call("between-graph-checkpoints")
    assert _loaded(tmp_path).snapshot().known_tokens == 5
    assert _loaded(tmp_path).snapshot().pending_calls == 1


@pytest.mark.unit
@pytest.mark.parametrize("damage", ["json", "unknown-field", "version", "run-id"])
def test_fr002_corrupt_durable_history_is_reported_without_resetting_it(tmp_path, damage):
    """REQ-TA-FR-002 D8: malformed history is never replaced with zero usage."""
    store = _store(tmp_path)
    state = RunBudgetTracker(100).export_state()
    store.save_state(state)
    altered = copy.deepcopy(state)
    if damage == "unknown-field":
        altered["prompt"] = "forbidden field"
    elif damage == "version":
        altered["version"] = 999
    elif damage == "run-id":
        altered["run_id"] = "different-run"
    encoded = "broken-json" if damage == "json" else json.dumps(altered)
    with sqlite3.connect(tmp_path / "checkpoints" / "NVDA.db") as conn:
        conn.execute("UPDATE budget_ledgers SET state_json = ?", (encoded,))
    with pytest.raises(BudgetLedgerError) as error:
        _store(tmp_path).load()
    assert error.value.reason_code == "BUDGET_LEDGER_INVALID"
    with sqlite3.connect(tmp_path / "checkpoints" / "NVDA.db") as conn:
        assert conn.execute("SELECT state_json FROM budget_ledgers").fetchone()[0] == encoded


@pytest.mark.unit
def test_fr002_new_tracker_cannot_overwrite_existing_history_without_explicit_restore(tmp_path):
    """REQ-TA-FR-002 D8: a fresh run must not erase matching-thread history."""
    _store(tmp_path).save_state(RunBudgetTracker(100).export_state())
    with pytest.raises(BudgetLedgerError) as error:
        _store(tmp_path).save_state(RunBudgetTracker(100).export_state())
    assert error.value.reason_code == "BUDGET_LEDGER_ALREADY_EXISTS"


@pytest.mark.unit
def test_fr002_competing_resumes_use_revision_compare_and_swap(tmp_path):
    """REQ-TA-FR-002 D8: two workers cannot overwrite cumulative observations."""
    _store(tmp_path).save_state(RunBudgetTracker(100).export_state())
    stores = [_store(tmp_path), _store(tmp_path)]
    trackers = [RunBudgetTracker.restore(store.load()) for store in stores]
    # This first commit deliberately invalidates the other revision.
    trackers[0].bind_persistence(stores[0].save_state)
    with pytest.raises(BudgetLedgerError) as error:
        trackers[1].bind_persistence(stores[1].save_state)
    assert error.value.reason_code == "BUDGET_LEDGER_CONFLICT"
    assert _loaded(tmp_path).snapshot().llm_calls == 0
    with pytest.raises(BudgetLedgerError):
        trackers[1].try_start(call_id="stale-call", phase="risk", role=CallRole.REQUIRED)


@pytest.mark.unit
def test_fr002_parallel_fresh_writers_cannot_both_claim_one_thread(tmp_path):
    """REQ-TA-FR-002 D8: an atomic insert chooses one owner without serializing LLMs."""
    stores = [_store(tmp_path), _store(tmp_path)]
    assert all(store.load() is None for store in stores)
    barrier = Barrier(2)

    def save(index):
        state = RunBudgetTracker(100, run_id=f"run-{index}").export_state()
        barrier.wait(timeout=10)
        try:
            stores[index].save_state(state)
        except BudgetLedgerError as error:
            return error.reason_code
        return "SAVED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, range(2)))
    assert sorted(outcomes) == ["BUDGET_LEDGER_CONFLICT", "SAVED"]


@pytest.mark.unit
@pytest.mark.parametrize("restore_in_place", [False, True])
def test_fr002_replayed_required_phase_is_an_optional_retry_after_resume(restore_in_place):
    """REQ-TA-FR-002 D4/D8: replay cannot get a second required-call exemption."""
    previous = RunBudgetTracker(5)
    previous.start_call("before-crash", "portfolio_manager")
    previous.finish_call("before-crash", _complete())
    if restore_in_place:
        tracker = RunBudgetTracker(5)
        tracker.restore_state(previous.export_state())
    else:
        tracker = RunBudgetTracker.restore(previous.export_state())
    assert not tracker.try_start(call_id="replay", phase="portfolio_manager", role=CallRole.REQUIRED).allowed
    assert tracker.try_start(call_id="new-phase", phase="new-required-synthesis", role=CallRole.REQUIRED).allowed


@pytest.mark.unit
def test_fr002_cleared_store_and_old_revision_cannot_resurrect_or_overwrite_a_run(tmp_path):
    """REQ-TA-FR-002 D5/D8: late events cannot revive a successfully cleared run."""
    first = _store(tmp_path)
    state = RunBudgetTracker(100, run_id="same-explicit-run-id").export_state()
    first.save_state(state)
    old_worker = _store(tmp_path)
    assert old_worker.load() == state
    first.clear()
    assert first.load() is None
    with pytest.raises(BudgetLedgerError) as error:
        first.save_state(state)
    assert error.value.reason_code == "BUDGET_LEDGER_CLOSED"

    replacement = _store(tmp_path)
    replacement.save_state(state)
    # Same run_id and revision still belong to a different row generation.
    for action in (lambda: old_worker.save_state(state), old_worker.clear):
        with pytest.raises(BudgetLedgerError) as error:
            action()
        assert error.value.reason_code == "BUDGET_LEDGER_CONFLICT"
    assert _loaded(tmp_path).export_state() == state


@pytest.mark.unit
def test_fr002_sqlite_write_failure_rolls_back_the_ledger_transaction(tmp_path):
    """REQ-TA-FR-002 D8: a failed write preserves the last committed whole state."""
    store = _store(tmp_path)
    tracker = RunBudgetTracker(100)
    store.save_state(tracker.export_state())
    before = _store(tmp_path).load()
    with sqlite3.connect(tmp_path / "checkpoints" / "NVDA.db") as conn:
        conn.execute("""CREATE TRIGGER reject_budget_update BEFORE UPDATE ON budget_ledgers
                        BEGIN SELECT RAISE(ABORT, 'fixture failure'); END""")
    tracker.finish_call("new-response", _complete())
    with pytest.raises(BudgetLedgerError) as error:
        store.save_state(tracker.export_state())
    assert error.value.reason_code == "BUDGET_LEDGER_WRITE_FAILED"
    assert _store(tmp_path).load() == before


@pytest.mark.unit
def test_fr002_ledgers_are_isolated_by_ticker_and_run_thread(tmp_path):
    """REQ-TA-FR-002 D8/QR-004: backtest cells do not inherit another allowance."""
    for tid, ticker, count in (("day-one", "NVDA", 1), ("day-two", "NVDA", 2), ("day-one", "MSFT", 3)):
        tracker = RunBudgetTracker(100)
        for i in range(count):
            tracker.finish_call(str(i), _complete())
        tracker.bind_persistence(_store(tmp_path, tid, ticker).save_state)
    assert _loaded(tmp_path, "day-one", "NVDA").snapshot().known_tokens == 5
    assert _loaded(tmp_path, "day-two", "NVDA").snapshot().known_tokens == 10
    assert _loaded(tmp_path, "day-one", "MSFT").snapshot().known_tokens == 15


@pytest.mark.unit
@pytest.mark.parametrize("ticker", ["../escape", "..\\escape", "C:\\escape"])
def test_fr002_budget_store_rejects_path_traversal_tickers(tmp_path, ticker):
    """REQ-TA-FR-002/INV-007: budget persistence honors safe ticker components."""
    with pytest.raises(ValueError):
        _store(tmp_path, ticker=ticker)
