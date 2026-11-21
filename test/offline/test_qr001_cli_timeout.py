"""Controlled failure at the CLI entry: provider timeout never prints a traceback (REQ-TA-QR-001).

The CLI streams the graph itself (it does not call ``propagate``). A provider
timeout that escapes the stream must be handled at the CLI entry: the run record
records ``run_metadata.failure.code = PROVIDER_TIMEOUT`` and the CLI exits with a
non-zero status and a safe message — no uncaught exception / traceback.
An unclassified exception still propagates (a genuine bug stays visible).
"""

from __future__ import annotations

import functools
import json

import pytest
import typer

import cli.run as cli_run
from tradingagents.graph.trading_graph import TradingAgentsGraph


class _TimeoutGraph:
    """A CLI graph double whose stream raises a classified provider timeout."""

    def __init__(self, tmp_path, exc):
        self.calls = []
        self.graph = self
        self.propagator = self
        self._resuming = False
        self.selected_analysts = ("market",)
        self.config = {"results_dir": str(tmp_path), "data_cache_dir": str(tmp_path / "c"),
                       "memory_log_path": str(tmp_path / "m.md")}
        self._exc = exc
        self._run_usage = None
        self._run_status = None
        self._run_started_at = None
        self._run_completed_at = None
        self._run_failure = None
        # Bind real record-writing methods.
        self.set_run_observations = functools.partial(
            TradingAgentsGraph.set_run_observations, self)
        self.write_run_record = functools.partial(
            TradingAgentsGraph.write_run_record, self)
        self.run_settings = functools.partial(TradingAgentsGraph.run_settings, self)
        self._budget_block = functools.partial(TradingAgentsGraph._budget_block, self)

    def create_run_state(self, ticker, trade_date, asset_type="stock", portfolio=None):
        return {"messages": [], "company_of_interest": ticker}

    def get_graph_args(self, callbacks=None):
        return {}

    def begin_checkpoint(self, *a, **k):
        return None

    def checkpoint_input(self, state):
        return state

    def end_checkpoint(self):
        pass

    def stream_run(self, graph_input, **kwargs):
        raise self._exc
        yield  # pragma: no cover


class _NullLive:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeBuffer:
    def __init__(self):
        self.messages = []
        self.tool_calls = []
        self.report_sections = {}
        self.agent_status = {}
        self.selected_analysts = []
        self._processed_message_ids = set()

    def init_for_analysis(self, analysts):
        self.selected_analysts = [a.lower() for a in analysts]

    def add_message(self, kind, content):
        self.messages.append((0.0, kind, content))

    def add_tool_call(self, name, args):
        self.tool_calls.append((0.0, name, args))

    def update_report_section(self, *a):
        pass

    def update_agent_status(self, *a):
        pass


def _drive(monkeypatch, tmp_path, graph):
    from cli.models import AnalystType

    monkeypatch.setattr(cli_run, "TradingAgentsGraph", lambda *a, **k: graph)
    monkeypatch.setattr(cli_run, "message_buffer", _FakeBuffer())
    monkeypatch.setattr(cli_run, "create_layout", lambda: None)
    monkeypatch.setattr(cli_run, "update_display", lambda *a, **k: None)
    monkeypatch.setattr(cli_run, "Live", _NullLive)
    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags=None: {
        "ticker": "NVDA", "analysis_date": "2026-01-10",
        "analysts": [AnalystType.MARKET], "asset_type": "stock",
    })
    monkeypatch.setattr(cli_run, "_build_run_config", lambda s, c, profile=None: graph.config)
    monkeypatch.setattr(cli_run.sys.stdin, "isatty", lambda: True)
    cli_run.run_analysis()


@pytest.mark.unit
def test_cli_provider_timeout_is_controlled_not_a_traceback(tmp_path, monkeypatch):
    """REQ-TA-QR-001 (D-CLI): a timeout at the CLI entry -> safe exit + PROVIDER_TIMEOUT record."""
    graph = _TimeoutGraph(tmp_path, TimeoutError("read timed out"))

    with pytest.raises(typer.Exit) as exited:   # typer.Exit, NOT TimeoutError
        _drive(monkeypatch, tmp_path, graph)
    assert exited.value.exit_code == 1

    record_path = tmp_path / "NVDA" / "TradingAgentsStrategy_logs" / "run_record_2026-01-10.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    assert data["run_metadata"]["status"] == "failed"
    assert data["run_metadata"]["failure"]["code"] == "PROVIDER_TIMEOUT"


@pytest.mark.unit
def test_cli_unclassified_exception_still_propagates(tmp_path, monkeypatch):
    """REQ-TA-QR-001: an unclassified exception is not swallowed by the CLI."""
    graph = _TimeoutGraph(tmp_path, RuntimeError("a real bug"))

    with pytest.raises(RuntimeError, match="a real bug"):
        _drive(monkeypatch, tmp_path, graph)
