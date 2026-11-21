"""Budget metadata in the run record, compatible with QR-004 (REQ-TA-FR-002; ADR-004).

Offline tests of the budget block placed under ``run_metadata.budget`` and of
its separation from the lifecycle ``status`` vocabulary. The report rendering
line is covered in the S3 slice; here the record contract is pinned.
"""

from __future__ import annotations

import json

import pytest

from tradingagents import run_record as record
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.run_budget import (
    USAGE_COMPLETE,
    CallRole,
    RunBudgetTracker,
    UsageObservation,
)


def _bare_graph(**config_overrides):
    graph = object.__new__(TradingAgentsGraph)
    graph.selected_analysts = ("market", "news")
    graph.config = {
        "llm_provider": "openai",
        "deep_think_llm": "gpt-6-sol",
        "quick_think_llm": "gpt-6-luna",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_rounds": 20,
        "output_language": "English",
        "data_vendors": {"core_stock_apis": "yfinance"},
        "tool_vendors": {},
        "token_budget": None,
        **config_overrides,
    }
    return graph


@pytest.mark.unit
def test_no_ledger_means_no_budget_block():
    """REQ-TA-QR-004: a bare instance (no scope ran) adds no budget block."""
    settings = _bare_graph().run_settings()
    assert "budget" not in settings["run_metadata"]


@pytest.mark.unit
def test_budget_block_and_token_budget_are_observational_not_replayable():
    """REQ-TA-FR-002 / FR-008: budget result and token_budget are observational.

    ``token_budget`` is an execution-time safety control: it is recorded under
    ``run_metadata`` (flat + ``run_metadata.token_budget``), never in
    ``replayable_settings``, so a QR-004 record stays replayable by FR-008.
    """
    graph = _bare_graph(token_budget=1000)
    graph._run_budget_tracker = RunBudgetTracker(1000)
    settings = graph.run_settings()
    assert "budget" in settings["run_metadata"]
    assert "budget" not in settings["replayable_settings"]
    assert "token_budget" not in settings["replayable_settings"]
    assert settings["run_metadata"]["token_budget"] == 1000
    assert settings["token_budget"] == 1000  # flat legacy observational key


@pytest.mark.unit
def test_lifecycle_status_unchanged_by_budget():
    """REQ-TA-FR-002 (D4): lifecycle status stays completed/failed; budget is separate."""
    graph = _bare_graph(token_budget=1000)
    graph._run_budget_tracker = RunBudgetTracker(1000)
    graph.set_run_observations(status=record.STATUS_COMPLETED)
    meta = graph.run_settings()["run_metadata"]
    assert meta["status"] == record.STATUS_COMPLETED
    assert meta["budget"]["status"] in ("BUDGET_OK", "BUDGET_WARNING", "BUDGET_EXHAUSTED")


@pytest.mark.unit
def test_budget_block_reports_status_and_reason():
    """REQ-TA-FR-002: the block carries status, limit and machine-readable reasons."""
    graph = _bare_graph(token_budget=100)
    tracker = RunBudgetTracker(100)
    tracker.start_call("a", role=CallRole.REQUIRED, phase="x")
    tracker.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    graph._run_budget_tracker = tracker
    block = graph.run_settings()["run_metadata"]["budget"]
    assert block["status"] == "BUDGET_EXHAUSTED"
    assert block["limit"] == 100
    assert block["reason_codes"]
    json.dumps(block)  # JSON-safe


@pytest.mark.unit
def test_unavailable_usage_renders_null_not_zero():
    """REQ-TA-FR-002 (D2): unavailable usage is null with usage_complete false."""
    graph = _bare_graph(token_budget=1000)
    graph._run_budget_tracker = RunBudgetTracker(1000)
    block = graph.run_settings()["run_metadata"]["budget"]
    assert block["usage_complete"] is False
    assert block["tokens_in"] is None and block["total_tokens"] is None


@pytest.mark.unit
def test_no_secret_or_path_in_budget_block():
    """REQ-TA-QR-004/FR-002: the block never carries endpoints, keys or local paths."""
    graph = _bare_graph(token_budget=500, backend_url="https://relay.invalid/v1",
                        results_dir="/path/should/not/appear")
    graph._run_budget_tracker = RunBudgetTracker(500)
    text = json.dumps(graph.run_settings()["run_metadata"]["budget"])
    assert "relay.invalid" not in text
    assert "/path/should/not/appear" not in text
    assert "api_key" not in text


@pytest.mark.unit
def test_report_header_renders_budget_line():
    """REQ-TA-FR-002: the markdown header renders the budget status and reason."""
    from tradingagents.reporting import _header

    graph = _bare_graph(token_budget=100)
    tracker = RunBudgetTracker(100)
    tracker.start_call("a", role=CallRole.REQUIRED, phase="x")
    tracker.finish_call("a", UsageObservation(80, 20, USAGE_COMPLETE))
    graph._run_budget_tracker = tracker
    header = _header("NVDA", {"trade_date": "2026-01-09"}, graph.run_settings())
    assert "Budget: BUDGET_EXHAUSTED" in header
    assert "limit 100" in header


@pytest.mark.unit
def test_report_header_has_no_budget_line_without_budget():
    """REQ-TA-FR-002: a run with no recorded budget block renders no Budget line."""
    from tradingagents.reporting import _header

    header = _header("NVDA", {"trade_date": "2026-01-09"}, _bare_graph().run_settings())
    assert "Budget:" not in header
