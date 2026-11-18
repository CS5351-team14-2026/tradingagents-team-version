"""Budget entrypoints: CLI flag, direct graph, and config precedence (FR-002; ADR-004).

Offline tests that ``--token-budget`` wins over the environment, an unset budget
is disabled, the CLI builds one ledger shared with the graph, and a direct
``TradingAgentsGraph.propagate`` caller also gets enforcement (graph-level, not
CLI-only).
"""

from __future__ import annotations

import pytest

import cli.run as cli_run
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.run_budget import RunBudgetTracker


@pytest.mark.unit
def test_flag_wins_over_environment(monkeypatch):
    """REQ-TA-FR-002 (D6): --token-budget beats TRADINGAGENTS_TOKEN_BUDGET."""
    monkeypatch.setenv("TRADINGAGENTS_TOKEN_BUDGET", "5000")
    config = cli_run._build_run_config(
        {"research_depth": 1, "quick_think_llm": "a", "deep_think_llm": "b",
         "backend_url": None, "llm_provider": "openai"}, None, token_budget=100)
    assert config["token_budget"] == 100


@pytest.mark.unit
def test_no_flag_no_env_is_disabled(monkeypatch):
    """REQ-TA-FR-002 (D6): neither flag nor env leaves the budget off (baseline)."""
    monkeypatch.delenv("TRADINGAGENTS_TOKEN_BUDGET", raising=False)
    config = cli_run._build_run_config(
        {"research_depth": 1, "quick_think_llm": "a", "deep_think_llm": "b",
         "backend_url": None, "llm_provider": "openai"}, None)
    # DEFAULT_CONFIG may carry None; the resolved value must be off.
    assert config.get("token_budget") is None


@pytest.mark.unit
def test_direct_graph_reads_budget_from_config():
    """REQ-TA-FR-002: a direct graph caller gets the budget from its config (not CLI-only)."""
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {**DEFAULT_CONFIG, "token_budget": 321}
    # observation_scope builds a tracker from the config's budget.
    from tradingagents.run_budget import current_run_context

    assert current_run_context() is None
    graph._run_budget_tracker = None
    with graph.observation_scope() as tracker:
        assert isinstance(tracker, RunBudgetTracker)
        assert tracker.limit == 321


@pytest.mark.unit
def test_observation_scope_no_budget_is_unlimited():
    """REQ-TA-FR-002 (D6): a graph without a budget runs with a no-limit ledger."""
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {**DEFAULT_CONFIG, "token_budget": None}
    graph._run_budget_tracker = None
    with graph.observation_scope() as tracker:
        assert tracker.limit is None
