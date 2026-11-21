"""Controlled failure: token budget exhausted is a defined, non-crashing end (REQ-TA-QR-001).

Offline tests: the budget result is ``BUDGET_EXHAUSTED`` (FR-002, ADR-004,
unchanged) and, when the run can only produce a non-tradeable REVIEW because the
budget ran out, the run record carries ``failure.code=TOKEN_BUDGET_EXHAUSTED``
under ``status=completed`` (ADR-005 D-D). No exception escapes.
"""

from __future__ import annotations

import functools
import json
from unittest.mock import MagicMock

import pytest

from tradingagents.failure import FailureCode
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.run_budget import (
    USAGE_COMPLETE,
    CallRole,
    RunBudgetTracker,
    UsageObservation,
)


def _exhausted_tracker():
    t = RunBudgetTracker(100)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    return t


def _minimal_graph(tmp_path):
    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market", "news")
    graph.config = {
        "llm_provider": "openai", "deep_think_llm": "gpt-6-sol",
        "quick_think_llm": "gpt-6-luna", "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1, "max_tool_rounds": 20,
        "output_language": "English", "data_vendors": {"core_stock_apis": "yfinance"},
        "tool_vendors": {}, "results_dir": str(tmp_path), "token_budget": 100,
    }
    return graph


@pytest.mark.unit
def test_budget_exhausted_block_is_safe_and_budget_status_mirrors():
    """REQ-TA-QR-001 (D-C/D-E): the code is closed and the diagnostic is safe."""
    from tradingagents.failure import build_failure

    block = build_failure(FailureCode.TOKEN_BUDGET_EXHAUSTED, phase="synthesis")
    assert block["code"] == "TOKEN_BUDGET_EXHAUSTED"
    assert "budget" in block["diagnostic"].lower()
    # The FR-002 budget status remains its own dimension.
    assert _exhausted_tracker().snapshot().status == "BUDGET_EXHAUSTED"


@pytest.mark.unit
def test_review_run_under_exhausted_budget_records_failure_mirror(tmp_path):
    """REQ-TA-QR-001: a REVIEW outcome with an exhausted budget records the mirror."""
    graph = MagicMock()
    graph.debug = False
    graph.config = _minimal_graph(tmp_path).config
    graph.profile_resolution = None
    graph._run_usage = None
    graph._run_status = None
    graph._run_started_at = None
    graph._run_completed_at = None
    graph._run_failure = None
    graph._run_budget_tracker = _exhausted_tracker()
    graph.create_run_state.return_value = {"company_of_interest": "NVDA", "trade_date": "2026-01-09"}
    graph.checkpoint_input.return_value = {}
    graph.propagator.get_graph_args.return_value = {}
    # A final state that yields REVIEW (no rating label in the decision text).
    graph.graph.invoke.return_value = {
        "company_of_interest": "NVDA",
        "final_trade_decision": "No recommendation could be produced.",
        "final_rating": "REVIEW",
    }
    graph.clear_checkpoint_on_success = MagicMock()
    graph.record_decision = MagicMock()
    for name in ("set_run_observations", "run_settings", "write_run_record", "_budget_block"):
        setattr(graph, name, functools.partial(getattr(TradingAgentsGraph, name), graph))

    state, rating = TradingAgentsGraph._run_graph(graph, "NVDA", "2026-01-09")

    assert rating == "REVIEW"
    meta = graph.run_settings()["run_metadata"]
    assert meta["status"] == "completed"            # D-D: degraded, not failed
    assert meta["failure"]["code"] == "TOKEN_BUDGET_EXHAUSTED"
    assert meta["budget"]["status"] == "BUDGET_EXHAUSTED"
    json.dumps(meta)                                 # record is JSON-safe


@pytest.mark.unit
def test_completed_run_without_exhaustion_has_no_failure_block(tmp_path):
    """REQ-TA-QR-001: a normal completed run carries no failure block."""
    graph = MagicMock()
    graph.debug = False
    graph.config = _minimal_graph(tmp_path).config
    graph.profile_resolution = None
    graph._run_usage = None
    graph._run_status = None
    graph._run_started_at = None
    graph._run_completed_at = None
    graph._run_failure = None
    graph._run_budget_tracker = None
    graph.create_run_state.return_value = {"company_of_interest": "NVDA", "trade_date": "2026-01-09"}
    graph.checkpoint_input.return_value = {}
    graph.propagator.get_graph_args.return_value = {}
    graph.graph.invoke.return_value = {
        "company_of_interest": "NVDA",
        "final_trade_decision": "**Rating**: Hold",
        "final_rating": "Hold",
    }
    graph.clear_checkpoint_on_success = MagicMock()
    graph.record_decision = MagicMock()
    for name in ("set_run_observations", "run_settings", "write_run_record", "_budget_block"):
        setattr(graph, name, functools.partial(getattr(TradingAgentsGraph, name), graph))

    TradingAgentsGraph._run_graph(graph, "NVDA", "2026-01-09")

    assert "failure" not in graph.run_settings()["run_metadata"]
