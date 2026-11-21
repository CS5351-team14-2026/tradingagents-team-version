"""Controlled failure: missing API key ends with a defined status, no escape (REQ-TA-QR-001).

Offline test: constructing the graph with a missing provider key raises a typed
``MissingApiKeyError`` (a ValueError subclass) that the CLI turns into a run
record with ``status=failed`` and ``run_metadata.failure.code=MISSING_API_KEY``.
No uncaught exception escapes; the record never contains the key value.
"""

from __future__ import annotations

import json

import pytest
import typer

import cli.run as cli_run
from tradingagents.failure import FailureCode, MissingApiKeyError
from tradingagents.graph import trading_graph


@pytest.mark.unit
def test_missing_key_error_is_a_value_error_with_code():
    """REQ-TA-QR-001: the typed error is catchable, carries only the env-var name."""
    err = MissingApiKeyError("DEEPSEEK_API_KEY", provider="deepseek")
    assert isinstance(err, ValueError)
    assert err.env_var == "DEEPSEEK_API_KEY"
    assert "DEEPSEEK_API_KEY" in str(err)
    block = err.to_failure()
    assert block["code"] == FailureCode.MISSING_API_KEY
    assert block["phase"] == "startup"


@pytest.mark.unit
def test_construction_without_key_raises_typed_error(monkeypatch):
    """REQ-TA-QR-001: graph construction raises the typed error, not an opaque ValueError."""
    # No DEEPSEEK_API_KEY in the environment -> the client refuses to build.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = {"llm_provider": "deepseek", "deep_think_llm": "deepseek-flash",
           "quick_think_llm": "deepseek-flash", "backend_url": None,
           "results_dir": "/tmp/qr1", "data_cache_dir": "/tmp/qr1c",
           "memory_log_path": "/tmp/qr1/m.md"}
    with pytest.raises(MissingApiKeyError) as caught:
        trading_graph.TradingAgentsGraph(config=cfg, selected_analysts=("market",))
    assert caught.value.env_var == "DEEPSEEK_API_KEY"


@pytest.mark.unit
def test_cli_writes_controlled_record_on_missing_key(monkeypatch, tmp_path):
    """REQ-TA-QR-001 (D-B): the CLI records MISSING_API_KEY and exits, no traceback."""

    def fake_graph(**kwargs):
        raise MissingApiKeyError("DEEPSEEK_API_KEY", provider="deepseek")

    # Drive run_analysis up to graph construction with a fake graph factory.
    monkeypatch.setattr(cli_run, "TradingAgentsGraph", fake_graph)
    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags: {
        "ticker": "NVDA", "asset_type": "stock", "analysis_date": "2026-01-09",
        "analysts": [], "research_depth": 1, "llm_provider": "deepseek",
        "backend_url": None, "quick_think_llm": "deepseek-flash",
        "deep_think_llm": "deepseek-flash", "output_language": "English",
    })
    monkeypatch.setattr(cli_run, "requested_profile", lambda flags: None)
    monkeypatch.setattr(cli_run, "_build_run_config", lambda *a, **k: {
        "results_dir": str(tmp_path), "data_cache_dir": str(tmp_path / "c"),
        "memory_log_path": str(tmp_path / "m.md"),
    })
    monkeypatch.setattr(cli_run.sys.stdin, "isatty", lambda: True)

    with pytest.raises(typer.Exit):
        cli_run.run_analysis()

    record_path = tmp_path / "NVDA" / "TradingAgentsStrategy_logs" / "run_record_2026-01-09.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    assert data["run_metadata"]["status"] == "failed"
    assert data["run_metadata"]["failure"]["code"] == "MISSING_API_KEY"
    assert "DEEPSEEK_API_KEY" not in json.dumps(data)  # only the env-var name may appear
