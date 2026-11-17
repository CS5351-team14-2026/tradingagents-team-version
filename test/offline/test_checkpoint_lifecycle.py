"""The checkpoint lifecycle is reusable so --checkpoint works on the CLI path (#1249).

Checkpoint setup previously lived only inside ``propagate``; the CLI streamed the
checkpointer-less graph, so ``--checkpoint`` neither saved nor resumed. The
lifecycle is now ``begin_checkpoint`` / ``end_checkpoint`` /
``clear_checkpoint_on_success`` on TradingAgentsGraph, used by both paths. These
tests drive that lifecycle exactly as the CLI does (begin -> stream self.graph ->
clear/end) and prove state is saved and resumed.
"""
from __future__ import annotations

import tempfile
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph

from tradingagents.graph.checkpointer import checkpoint_step, get_checkpointer, thread_id
from tradingagents.graph.trading_graph import TradingAgentsGraph

_should_crash = False


class _State(TypedDict):
    count: int


def _node_a(state: _State) -> dict:
    return {"count": state["count"] + 1}


def _node_b(state: _State) -> dict:
    if _should_crash:
        raise RuntimeError("simulated mid-stream crash")
    return {"count": state["count"] + 10}


def _workflow() -> StateGraph:
    b = StateGraph(_State)
    b.add_node("analyst", _node_a)
    b.add_node("trader", _node_b)
    b.set_entry_point("analyst")
    b.add_edge("analyst", "trader")
    b.add_edge("trader", END)
    return b


def _bare_graph(tmpdir, *, enabled=True):
    g = object.__new__(TradingAgentsGraph)
    g.config = {
        "checkpoint_enabled": enabled, "data_cache_dir": tmpdir,
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1,
    }
    g.selected_analysts = ("market",)
    g.workflow = _workflow()
    g.graph = g.workflow.compile()
    g._checkpointer_ctx = None
    return g


@pytest.mark.unit
def test_disabled_is_a_noop():
    with tempfile.TemporaryDirectory() as tmp:
        g = _bare_graph(tmp, enabled=False)
        plain = g.graph
        assert g.begin_checkpoint("AAPL", "2026-05-08", "stock") is None
        assert g.graph is plain  # graph not recompiled
        g.end_checkpoint()  # safe no-op


@pytest.mark.unit
def test_begin_returns_thread_id_and_recompiles():
    with tempfile.TemporaryDirectory() as tmp:
        g = _bare_graph(tmp)
        plain = g.graph
        tid = g.begin_checkpoint("AAPL", "2026-05-08", "stock")
        try:
            assert tid  # a real thread_id
            assert g.graph is not plain  # recompiled with a checkpointer
        finally:
            g.end_checkpoint()
        assert g._checkpointer_ctx is None  # restored


@pytest.mark.unit
def test_checkpoint_input_is_none_only_when_resuming():
    global _should_crash
    with tempfile.TemporaryDirectory() as tmp:
        init = {"count": 0}
        args = ("AAPL", "2026-05-08", "stock")
        # Fresh run: no checkpoint yet -> stream the initial state, then crash.
        g1 = _bare_graph(tmp)
        tid = g1.begin_checkpoint(*args)
        try:
            assert g1._resuming is False
            assert g1.checkpoint_input(init) is init  # not resuming -> initial state
            _should_crash = True
            with pytest.raises(RuntimeError):
                for _ in g1.graph.stream(init, config={"configurable": {"thread_id": tid}}):
                    pass
        finally:
            g1.end_checkpoint()
        assert g1.checkpoint_input(init) is init  # reset after teardown

        # A later run finds the checkpoint -> resume by feeding None, not the
        # initial state (re-passing it would duplicate messages, #1249).
        _should_crash = False
        g2 = _bare_graph(tmp)
        g2.begin_checkpoint(*args)
        try:
            assert g2._resuming is True
            assert g2.checkpoint_input(init) is None
        finally:
            g2.end_checkpoint()


@pytest.mark.unit
def test_cli_style_usage_saves_then_resumes():
    global _should_crash
    with tempfile.TemporaryDirectory() as tmp:
        cfg_args = ("AAPL", "2026-05-08", "stock")

        # Run 1 (the CLI path): begin -> stream self.graph -> crash at 'trader'.
        _should_crash = True
        g1 = _bare_graph(tmp)
        tid = g1.begin_checkpoint(*cfg_args)
        args = {"config": {"configurable": {"thread_id": tid}}}
        try:
            with pytest.raises(RuntimeError):
                for _ in g1.graph.stream({"count": 0}, **args):
                    pass
        finally:
            g1.end_checkpoint()

        # A checkpoint was saved for this run signature (so --checkpoint works).

        sig = g1._run_signature("stock")
        assert checkpoint_step(tmp, "AAPL", "2026-05-08", sig) is not None

        # Run 2 (fresh graph, as a new CLI invocation): resume and finish.
        _should_crash = False
        g2 = _bare_graph(tmp)
        tid2 = g2.begin_checkpoint(*cfg_args)
        assert tid2 == tid  # stable id -> same thread resumes
        try:
            result = g2.graph.invoke(None, config={"configurable": {"thread_id": tid2}})
            assert result["count"] == 11  # analyst(+1) resumed into trader(+10)
            g2.clear_checkpoint_on_success(*cfg_args)
        finally:
            g2.end_checkpoint()

        # Cleared on success -> a later run starts fresh.
        assert checkpoint_step(tmp, "AAPL", "2026-05-08", sig) is None


@pytest.mark.unit
def test_clearing_removes_the_database_sidecars(tmp_path):
    """SQLite writes -wal and -shm next to the database; leaving them behind
    means a cleared checkpoint still has committed state on disk."""
    from tradingagents.graph.checkpointer import clear_all_checkpoints

    cp = tmp_path / "checkpoints"
    cp.mkdir(parents=True)
    for suffix in (".db", ".db-wal", ".db-shm"):
        (cp / f"NVDA{suffix}").write_text("x")

    cleared = clear_all_checkpoints(str(tmp_path))

    assert cleared == 1
    assert list(cp.iterdir()) == []


# Fixed checkpoint signatures computed independently from the two historical
# commits — NOT from the current helper. Each is the exact string that commit's
# ``_run_signature`` produced for the lifecycle graph's baseline config
# (max_debate_rounds=1, max_risk_discuss_rounds=1, one ``market`` analyst,
# asset=stock, no portfolio):
#
#   03e7d48 (pre-PR#27 baseline; no ``claim_enforcement`` key at all)
#     settings digest = sha256 of {"max_debate_rounds":1,"max_risk_discuss_rounds":1}
#     minus {results_dir, data_cache_dir, memory_log_path, checkpoint_enabled,
#     llm_max_retries} = d97f1c2e38c4.
#   fba0315 (integration right after PR #27; ``claim_enforcement=False`` present
#     in the config and still part of the digest) = settings digest 47a2585a7c9b.
#
# This build stores a default run under the 03e7d48 value (``claim_enforcement``
# dropped) and, when resuming, falls back to the fba0315 value (key folded in at
# its historical ``False``, even though the current default is now ``True``).
_SIGNATURE_03e7d48 = (
    "analysts=market|debate=1|risk=1|asset=stock|portfolio=none|"
    "analysts=parallel|memory=parallel|settings=d97f1c2e38c4"
)
_SIGNATURE_fba0315 = (
    "analysts=market|debate=1|risk=1|asset=stock|portfolio=none|"
    "analysts=parallel|memory=parallel|settings=47a2585a7c9b"
)


def _config_with_current_claim_enforcement(tmpdir, **extra):
    """A lifecycle graph whose config carries the *current* ``claim_enforcement``
    default (``True``) — so resume must still reach the PR #27 ``False`` thread."""
    g = _bare_graph(tmpdir)
    g.config = {
        "checkpoint_enabled": True, "data_cache_dir": tmpdir,
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1,
        "claim_enforcement": True, **extra,
    }
    return g


@pytest.mark.unit
def test_a_03e7d48_checkpoint_resumes_and_is_cleared_on_success(tmp_path):
    """REQ-TA-FR-001: a checkpoint written under the 03e7d48 (pre-PR#27)
    signature still resumes, and finishing the run clears that thread so a later
    run starts fresh. The expected signature is the fixed historical value."""
    global _should_crash
    args = ("AAPL", "2026-05-08", "stock")

    # Write an interrupted checkpoint under the *fixed* pre-PR#27 thread, exactly
    # as a run from commit 03e7d48 would have left it.
    writer = _config_with_current_claim_enforcement(str(tmp_path))
    old_thread = thread_id("AAPL", "2026-05-08", _SIGNATURE_03e7d48)
    _should_crash = True
    with get_checkpointer(str(tmp_path), "AAPL") as saver:
        compiled = writer.workflow.compile(checkpointer=saver)
        with pytest.raises(RuntimeError):
            compiled.invoke({"count": 0}, config={"configurable": {"thread_id": old_thread}})

    assert checkpoint_step(str(tmp_path), "AAPL", "2026-05-08", _SIGNATURE_03e7d48) is not None

    # A later run resumes via that historical thread, finishes and clears it.
    _should_crash = False
    resume = _config_with_current_claim_enforcement(str(tmp_path))
    tid = resume.begin_checkpoint(*args)
    try:
        assert resume._resuming is True
        assert tid == old_thread             # resumed through the historical thread
        assert resume.checkpoint_input({"count": 0}) is None
        result = resume.graph.invoke(None, config={"configurable": {"thread_id": tid}})
        assert result["count"] == 11         # analyst(+1) resumed into trader(+10)
        resume.clear_checkpoint_on_success(*args)
    finally:
        resume.end_checkpoint()

    # Cleared on success: the historical signature is not left behind.
    assert checkpoint_step(str(tmp_path), "AAPL", "2026-05-08", _SIGNATURE_03e7d48) is None


@pytest.mark.unit
def test_a_fba0315_checkpoint_resumes_even_when_claim_enforcement_is_now_true(tmp_path):
    """REQ-TA-FR-001: with the current ``claim_enforcement=True`` default, a
    checkpoint saved by integration right after PR #27 (``claim_enforcement=False``
    in the digest) still resumes via the fallback, which folds in the historical
    ``False``. Finishing the run clears it. The expected signature is the fixed
    historical value."""
    global _should_crash
    args = ("AAPL", "2026-05-08", "stock")

    # The writer that left the PR #27 checkpoint ran when the key defaulted to
    # False; the current default is True, but the stored thread is unchanged.
    writer = _bare_graph(str(tmp_path))
    writer.config = {
        "checkpoint_enabled": True, "data_cache_dir": str(tmp_path),
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1, "claim_enforcement": False,
    }
    new_thread = thread_id("AAPL", "2026-05-08", _SIGNATURE_fba0315)
    _should_crash = True
    with get_checkpointer(str(tmp_path), "AAPL") as saver:
        compiled = writer.workflow.compile(checkpointer=saver)
        with pytest.raises(RuntimeError):
            compiled.invoke({"count": 0}, config={"configurable": {"thread_id": new_thread}})

    assert checkpoint_step(str(tmp_path), "AAPL", "2026-05-08", _SIGNATURE_fba0315) is not None

    # The current build (claim_enforcement=True) resumes that legacy thread.
    _should_crash = False
    resume = _config_with_current_claim_enforcement(str(tmp_path))
    tid = resume.begin_checkpoint(*args)
    try:
        assert resume._resuming is True
        assert tid == new_thread
        assert resume.checkpoint_input({"count": 0}) is None
        result = resume.graph.invoke(None, config={"configurable": {"thread_id": tid}})
        assert result["count"] == 11
        resume.clear_checkpoint_on_success(*args)
    finally:
        resume.end_checkpoint()

    assert checkpoint_step(str(tmp_path), "AAPL", "2026-05-08", _SIGNATURE_fba0315) is None


@pytest.mark.unit
def test_a_historical_checkpoint_is_not_resumed_when_the_run_settings_differ(tmp_path):
    """REQ-TA-FR-001: neither historical fallback resumes on a settings mismatch.
    A checkpoint saved with a different model must not be picked up."""
    global _should_crash
    args = ("AAPL", "2026-05-08", "stock")

    # The fixed historical threads were written for a baseline config with no
    # model set; a config naming a different model (``q1`` here) digests
    # differently, so neither thread can be the one this resume looks for.
    writer = _config_with_current_claim_enforcement(str(tmp_path), quick_think_llm="q1")
    old_thread = thread_id("AAPL", "2026-05-08", _SIGNATURE_03e7d48)
    new_thread = thread_id("AAPL", "2026-05-08", _SIGNATURE_fba0315)
    _should_crash = True
    with get_checkpointer(str(tmp_path), "AAPL") as saver:
        compiled = writer.workflow.compile(checkpointer=saver)
        for tid in (old_thread, new_thread):
            with pytest.raises(RuntimeError):
                compiled.invoke({"count": 0}, config={"configurable": {"thread_id": tid}})

    # A different model is a different run: neither checkpoint is used.
    _should_crash = False
    resume = _config_with_current_claim_enforcement(str(tmp_path), quick_think_llm="q2")
    tid = resume.begin_checkpoint(*args)
    try:
        assert resume._resuming is False
        assert tid not in (old_thread, new_thread)
    finally:
        resume.end_checkpoint()
