"""S1 observation wiring (REQ-TA-FR-002; REQ-TA-QR-004/005; ADR-003).

The existing scripted graph and CLI doubles exercise real LangChain callbacks.
No budget routing or token-budget configuration is enabled in this stage.
"""

from __future__ import annotations

import json

import pytest
from rich.console import Console

from cli import display
from cli.stats_handler import StatsCallbackHandler
from tradingagents import run_record
from tradingagents.graph import trading_graph
from tradingagents.run_budget import (
    RunBudgetContext,
    RunBudgetTracker,
    UsageObservation,
    current_run_context,
)

from . import test_cli_profile_e2e as cli_doubles, test_graph_end_to_end as graph_doubles

offline = graph_doubles.offline


class UsageModel(graph_doubles.ScriptedModel):
    """The existing tool/graph double, with provider-reported token counts."""

    usage_mode: str = "complete"

    def _generate(self, *args, **kwargs):
        result = super()._generate(*args, **kwargs)
        message = result.generations[0].message
        if self.usage_mode == "complete":
            message.usage_metadata = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        elif self.usage_mode == "partial":
            message.response_metadata = {"token_usage": {"prompt_tokens": 3}}
        return result


def _client_factory(model):
    def create(config, tier, **kwargs):
        return graph_doubles._Client(model.model_copy(update={"callbacks": kwargs.get("callbacks")}))
    return create


def _graph(tmp_path, monkeypatch, model, callbacks=None):
    cfg = dict(graph_doubles.DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "memory.md"))
    monkeypatch.setattr(trading_graph, "create_tier_client", _client_factory(model))
    return trading_graph.TradingAgentsGraph(config=cfg, callbacks=callbacks)


@pytest.mark.unit
def test_fr002_direct_graph_observes_all_calls_without_double_counting(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-004: direct graph users get the same measured ledger."""
    model = UsageModel()
    stats = StatsCallbackHandler()
    graph = _graph(tmp_path, monkeypatch, model, [stats])

    state, signal = graph.propagate("NVDA", graph_doubles.TRADE_DATE)

    metadata = graph.run_settings()["run_metadata"]
    assert signal == state["final_rating"] == "Overweight"
    assert metadata["llm_calls"] == len(model.calls)
    assert metadata["tokens_in"] == 3 * len(model.calls)
    assert metadata["tokens_out"] == 2 * len(model.calls)
    assert metadata["total_tokens"] == 5 * len(model.calls)
    assert metadata["usage_complete"] is True
    assert metadata["tool_calls"] > 0
    assert stats.get_stats()["llm_calls"] == metadata["llm_calls"]
    assert current_run_context() is None
    log = next((tmp_path / "results").rglob("full_states_log_*.json"))
    assert json.loads(log.read_text(encoding="utf-8"))["run_settings"]["run_metadata"] == metadata


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["partial", "unavailable"])
def test_fr002_partial_or_missing_usage_is_never_a_complete_zero(
        tmp_path, monkeypatch, offline, mode):
    """REQ-TA-FR-002/QR-004: incomplete provider reports persist as incomplete."""
    model = UsageModel(usage_mode=mode)
    graph = _graph(tmp_path, monkeypatch, model)
    graph.propagate("NVDA", graph_doubles.TRADE_DATE)

    metadata = graph.run_settings()["run_metadata"]
    assert metadata["llm_calls"] == len(model.calls)
    assert metadata["usage_complete"] is False
    assert metadata["tokens_out"] is None
    assert metadata["total_tokens"] is None
    assert metadata["tokens_in"] == (3 * len(model.calls) if mode == "partial" else None)
    assert metadata["status"] == run_record.STATUS_COMPLETED


@pytest.mark.unit
def test_fr002_reused_graph_starts_a_fresh_observational_ledger(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002: reused backtest graph cells cannot inherit old counts."""
    model = UsageModel()
    graph = _graph(tmp_path, monkeypatch, model)
    graph.propagate("NVDA", graph_doubles.TRADE_DATE)
    previous_calls = len(model.calls)
    # Reflection semantics are tested separately; keep this a fixed repeat run.
    monkeypatch.setattr(graph, "settle_all_pending", lambda **kwargs: trading_graph.settlement.Settlement())
    graph.propagate("NVDA", graph_doubles.TRADE_DATE)

    metadata = graph.run_settings()["run_metadata"]
    assert metadata["llm_calls"] == len(model.calls) - previous_calls
    assert metadata["total_tokens"] == 5 * metadata["llm_calls"]


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["settle_pending", "settle_all_pending"])
def test_fr002_standalone_settlement_cannot_charge_the_last_analysis(
        tmp_path, monkeypatch, offline, operation):
    """REQ-TA-FR-002 D9: standalone/backtest-tail reflection has a separate ledger."""
    graph = _graph(tmp_path, monkeypatch, UsageModel())
    graph.propagate("NVDA", graph_doubles.TRADE_DATE)
    analysis_tracker = graph.usage_handler.tracker
    analysis_snapshot = analysis_tracker.snapshot()
    analysis_metadata = graph.run_settings()["run_metadata"]

    def reflect(*args, **kwargs):
        graph.quick_thinking_llm.invoke("Offline settlement fixture")
        return trading_graph.settlement.Settlement()

    monkeypatch.setattr(trading_graph.settlement, operation, reflect)
    args = ["NVDA"] if operation == "settle_pending" else []
    getattr(graph, operation)(*args)
    settlement_tracker = graph.usage_handler.tracker
    assert settlement_tracker is not analysis_tracker
    assert settlement_tracker.snapshot().total_tokens == 5
    assert analysis_tracker.snapshot() == analysis_snapshot
    assert graph.run_settings()["run_metadata"] == analysis_metadata
    assert current_run_context() is None


@pytest.mark.unit
def test_fr002_failure_records_observed_usage_and_preserves_failure_contract(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-004: S1 observes errors without altering provider failure behaviour."""
    graph = _graph(tmp_path, monkeypatch, UsageModel(fail_at=1))
    with pytest.raises(RuntimeError, match="provider unavailable"):
        graph.propagate("NVDA", graph_doubles.TRADE_DATE)
    metadata = graph.run_settings()["run_metadata"]
    assert metadata["status"] == run_record.STATUS_FAILED
    assert metadata["llm_calls"] >= 1
    assert metadata["usage_complete"] is False
    assert metadata["total_tokens"] is None
    assert current_run_context() is None
    record = next((tmp_path / "results").rglob("run_record_*.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["run_metadata"]["status"] == "failed"


@pytest.mark.unit
def test_fr002_real_cli_and_graph_share_one_observational_ledger(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-004: constructor and stream callbacks do not double charge CLI runs."""
    model = UsageModel()
    monkeypatch.setattr(trading_graph, "create_tier_client", _client_factory(model))
    _, graph = cli_doubles._drive(
        monkeypatch, tmp_path, "NVDA", "stock", "quick", ["market", "news"])
    metadata = graph.run_settings()["run_metadata"]
    assert metadata["status"] == "completed"
    assert metadata["llm_calls"] == len(model.calls)
    assert metadata["usage_complete"] is True
    assert metadata["total_tokens"] == 5 * len(model.calls)
    assert current_run_context() is None


@pytest.mark.unit
def test_fr002_observation_scope_restores_an_enclosing_context(tmp_path, monkeypatch, offline):
    """REQ-TA-QR-003/005: graph uses a public context and never leaks it to another run."""
    graph = _graph(tmp_path, monkeypatch, UsageModel())
    tracker = RunBudgetTracker()
    context = RunBudgetContext(tracker)
    with context.activate():
        with graph.observation_scope() as shared:
            assert shared is tracker
        assert current_run_context() is context
    assert current_run_context() is None


@pytest.mark.unit
def test_fr002_qr004_explicit_incomplete_usage_cannot_be_reclassified():
    """REQ-TA-FR-002/QR-004: known component counts do not prove complete usage."""
    usage = run_record.build_usage_summary({
        "tokens_in": 3, "tokens_out": 2, "usage_complete": False,
    })
    assert usage.tokens_in == 3 and usage.tokens_out == 2
    assert usage.usage_complete is False
    assert usage.total_tokens is None


@pytest.mark.unit
def test_fr002_another_graph_context_cannot_replace_saved_run_metadata(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-004: a graph only reads its own active observations."""
    graph = _graph(tmp_path, monkeypatch, UsageModel())
    graph.set_run_observations(usage=run_record.build_usage_summary({
        "tokens_in": 3, "tokens_out": 2,
    }))
    unrelated = RunBudgetTracker()
    unrelated.finish_call("other", UsageObservation(100, 50, state="complete"))
    with RunBudgetContext(unrelated).activate():
        assert graph.run_settings()["run_metadata"]["total_tokens"] == 5


@pytest.mark.unit
def test_fr002_resumed_history_is_not_replaced_by_a_complete_zero_or_remainder(
        tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-004: S1 marks pre-checkpoint usage unknown until S3 restoration."""
    model = UsageModel(fail_at=1)
    graph = _graph(tmp_path, monkeypatch, model)
    graph.config["checkpoint_enabled"] = True
    with pytest.raises(RuntimeError, match="provider unavailable"):
        graph.propagate("NVDA", graph_doubles.TRADE_DATE)
    # Bound copies share the call list, so the failure only occurs once.
    graph.propagate("NVDA", graph_doubles.TRADE_DATE)
    metadata = graph.run_settings()["run_metadata"]
    assert metadata["status"] == "completed"
    assert metadata["llm_calls"] > 0
    assert metadata["tokens_in"] > 0
    assert metadata["usage_complete"] is False
    assert metadata["total_tokens"] is None
    # The footer explicitly labels this invocation's observations, while the
    # canonical record leaves the resumed full-run usage incomplete.
    layout = display.create_layout()
    display.update_display(layout, stats_handler=graph.usage_handler)
    console = Console(width=200, height=60)
    with console.capture() as captured:
        console.print(layout)
    assert "Tokens (observed):" in captured.get()
    assert metadata["budget"]["usage_state"] == "partial"


@pytest.mark.unit
@pytest.mark.parametrize("stats, expected", [
    ({"llm_calls": 1, "tool_calls": 0, "tokens_in": None, "tokens_out": None,
      "usage_complete": False}, "Tokens (observed): unavailable"),
    ({"llm_calls": 1, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0,
      "usage_complete": True}, "Tokens (observed): 0"),
])
def test_fr002_cli_distinguishes_unavailable_usage_from_reported_zero(stats, expected):
    """REQ-TA-FR-002/QR-004: nullable usage is safe and honest in the live footer."""
    handler = type("Stats", (), {"get_stats": lambda self: stats})()
    layout = display.create_layout()
    display.update_display(layout, stats_handler=handler)
    console = Console(record=True, width=200, height=60)
    with console.capture() as captured:
        console.print(layout)
    assert expected in captured.get()
