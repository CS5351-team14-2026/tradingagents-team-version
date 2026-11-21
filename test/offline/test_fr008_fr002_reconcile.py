"""FR-008 + FR-002 reconciliation contract (Implements: REQ-TA-FR-008, REQ-TA-FR-002).

These offline tests pin the combined behaviour after FR-002 (per-run token
budget) merged into integration:

- a replayed run uses the SAME single budget tracker (no duplicate accounting);
- token_budget is an execution-time control: it may be combined with
  --from-settings, but it is never replayed from the prior record;
- validation of a replay record fails BEFORE any tracker/provider construction;
- run_metadata.budget stays observational and cannot override replay config.

All fixtures are synthetic; no live provider calls.
"""

from __future__ import annotations

import json

import pytest

from tradingagents import run_record as record
from tradingagents.settings_replay import ALLOWED_KEYS, load_replayable_settings

VALID = {
    "profile": "quick",
    "analysts": ["market", "news"],
    "llm_provider": "deepseek",
    "deep_think_provider": None,
    "quick_think_provider": None,
    "deep_think_llm": "deepseek-flash",
    "quick_think_llm": "deepseek-flash",
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_tool_rounds": 3,
    "temperature": None,
    "openai_reasoning_effort": None,
    "google_thinking_level": None,
    "anthropic_effort": None,
    "output_language": "English",
    "data_vendors": {"core_stock_apis": "yfinance"},
    "tool_vendors": {},
}


def _root(path, **overrides):
    rec = {"schema_version": "1", "replayable_settings": dict(VALID)}
    rec["replayable_settings"].update(overrides)
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


@pytest.mark.unit
def test_token_budget_not_in_fr008_allowlist():
    """REQ-TA-FR-008/FR-002: token_budget is not part of the replay allowlist."""
    assert "token_budget" not in ALLOWED_KEYS


@pytest.mark.unit
def test_run_metadata_budget_is_not_replayable():
    """FR-002 budget lives under run_metadata and never reaches replayable settings."""
    rec = record.build_run_record(
        replayable_settings=dict(VALID),
        budget={"status": "BUDGET_OK", "limit": 1000},
        version="0.7.1",
    ).to_dict()
    assert "budget" in rec["run_metadata"]
    assert "token_budget" not in rec["replayable_settings"]
    assert "budget" not in rec["replayable_settings"]


@pytest.mark.unit
def test_replay_of_record_with_budget_ignores_it(tmp_path):
    """FR-008: a record carrying run_metadata.budget replays without it."""
    rec = {
        "schema_version": "1",
        "replayable_settings": dict(VALID),
        "run_metadata": {"budget": {"status": "BUDGET_WARNING", "limit": 500},
                         "status": "completed"},
    }
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    loaded = load_replayable_settings(p)
    assert "token_budget" not in loaded.effective_settings()
    assert "budget" not in loaded.effective_settings()


@pytest.mark.unit
def test_invalid_replay_fails_before_tracker_construction(tmp_path, monkeypatch):
    """FR-008: validation fails before StatsCallbackHandler/RunBudgetTracker exist."""
    import cli.run as cli_run

    built = {"stats": 0, "tracker": 0}

    class _BoomStats:
        def __init__(self, *a, **k):
            built["stats"] += 1
            raise AssertionError("StatsCallbackHandler must not be built on invalid replay")

    # Invalid record: unknown field
    bad = _root(tmp_path / "bad.json")
    data = json.loads(bad.read_text())
    data["replayable_settings"]["token_budget"] = 5
    bad.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(cli_run, "StatsCallbackHandler", _BoomStats)
    import typer
    with pytest.raises((SystemExit, typer.Exit)):
        cli_run.run_analysis(
            flags={"from_settings": str(bad), "ticker": "AAPL", "date": "2026-11-16"},
        )
    assert built["stats"] == 0


@pytest.mark.unit
def test_replay_plus_budget_single_shared_tracker(tmp_path, monkeypatch):
    """FR-008+FR-002: one tracker is built and budget reaches runtime config."""
    import cli.run as cli_run

    good = _root(tmp_path / "good.json")
    seen = {"calls": 0}

    class _Sentinel(Exception):
        pass

    def _spy_stats(tracker=None):
        seen["calls"] += 1
        seen["tracker"] = tracker
        # config is already built at this point; capture it via the tracker limit.
        seen["tracker_limit"] = getattr(tracker, "limit", "n/a")
        raise _Sentinel("stop after single tracker construction")

    monkeypatch.setattr(cli_run, "StatsCallbackHandler", _spy_stats)
    with pytest.raises(_Sentinel):
        cli_run.run_analysis(
            flags={"from_settings": str(good), "ticker": "AAPL", "date": "2026-11-16",
                   "save": False, "show": False},
            token_budget=1234,
        )
    assert seen["calls"] == 1  # exactly one tracker/handler, no duplicate
    assert seen["tracker_limit"] == 1234  # budget came from the new invocation
