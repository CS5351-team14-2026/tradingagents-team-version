"""Budget in checkpoint resume identity (REQ-TA-FR-002; ADR-004 D6).

Offline tests of the checkpoint signature: a no-budget run keeps the historical
(pre-FR-002) signature byte-for-byte, an enabled budget changes it so a resume
cannot restore a mismatched budget, and the ledger's history-unavailable flag
reports honestly on a legacy resume.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.run_budget import (
    CallRole,
    RunBudgetTracker,
)

_NOT_IN_SIGNATURE = frozenset({
    "results_dir", "data_cache_dir", "memory_log_path", "checkpoint_enabled",
    "llm_max_retries", "claim_enforcement",
})


def _bare_graph(**overrides):
    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market", "news")
    graph.config = {**DEFAULT_CONFIG, **overrides}
    graph.profile_resolution = None
    return graph


def _reference_digest(config):
    """The historical digest: excludes token_budget when it is None (absent at 03e7d48)."""
    settings = {
        k: v for k, v in config.items()
        if k not in _NOT_IN_SIGNATURE and not (k == "token_budget" and v is None)
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()[:12]


@pytest.mark.unit
def test_no_budget_signature_unchanged():
    """REQ-TA-FR-002 (D6): a no-budget run keeps the pre-change signature."""
    g = _bare_graph(token_budget=None)
    sig = g._run_signature("stock")
    assert f"settings={_reference_digest(g.config)}" in sig


@pytest.mark.unit
def test_budget_changes_the_signature():
    """REQ-TA-FR-002 (D6): enabling a budget yields a distinct checkpoint signature."""
    plain = _bare_graph(token_budget=None)._run_signature("stock")
    budgeted = _bare_graph(token_budget=1000)._run_signature("stock")
    assert plain != budgeted


@pytest.mark.unit
def test_two_budgets_differ():
    """REQ-TA-FR-002 (D6): two different budgets never share a signature."""
    a = _bare_graph(token_budget=1000)._run_signature("stock")
    b = _bare_graph(token_budget=2000)._run_signature("stock")
    assert a != b


@pytest.mark.unit
def test_history_unavailable_reports_warning():
    """REQ-TA-FR-002 (D8): a legacy resume with no ledger history reports honestly, not as zero."""
    t = RunBudgetTracker(1000)
    t.mark_history_unavailable()
    snap = t.snapshot()
    assert snap.status == "BUDGET_WARNING"
    assert "USAGE_HISTORY_UNAVAILABLE" in snap.reason_codes
    assert snap.tokens_in is None
    assert t.try_start(call_id="x", role=CallRole.OPTIONAL, phase="d").allowed is False
