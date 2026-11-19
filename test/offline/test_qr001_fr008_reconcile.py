"""QR-001 failure record stays compatible with FR-008 replay (REQ-TA-QR-001; FR-008).

The controlled-failure block lives under ``run_metadata.failure`` — observational,
never in ``replayable_settings`` — so a record produced by a failed run (or any
run) is still replayable by REQ-TA-FR-008, which reads only
``replayable_settings`` + ``schema_version``. These offline tests pin that.
"""

from __future__ import annotations

import json

import pytest

from tradingagents import run_record as record
from tradingagents.failure import FailureCode, build_failure
from tradingagents.settings_replay import ALLOWED_KEYS, load_replayable_settings

_VALID_REPLAYABLE = {
    "profile": "quick",
    "analysts": ["market", "news"],
    "llm_provider": "openai",
    "deep_think_provider": None,
    "quick_think_provider": None,
    "deep_think_llm": "gpt-6-sol",
    "quick_think_llm": "gpt-6-luna",
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_tool_rounds": 20,
    "temperature": None,
    "openai_reasoning_effort": None,
    "google_thinking_level": None,
    "anthropic_effort": None,
    "output_language": "English",
    "data_vendors": {"core_stock_apis": "yfinance"},
    "tool_vendors": {},
}


@pytest.mark.unit
def test_failure_and_budget_are_not_replayable_fields():
    """REQ-TA-QR-001 / FR-008: failure/budget/token_budget never enter replayable."""
    for key in ("failure", "budget", "token_budget"):
        assert key not in ALLOWED_KEYS


@pytest.mark.unit
def test_record_with_failure_block_is_still_replayable(tmp_path):
    """REQ-TA-QR-001: a failed run's record replays (failure is observational)."""
    rec = record.build_run_record(
        replayable_settings=dict(_VALID_REPLAYABLE),
        status=record.STATUS_FAILED,
        failure=build_failure(FailureCode.PROVIDER_TIMEOUT, phase="run",
                              exception_type="TimeoutError"),
        token_budget=500,
        version="0.7.1",
    ).to_dict()
    assert "failure" in rec["run_metadata"]
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(rec), encoding="utf-8")

    loaded = load_replayable_settings(p)   # must not raise
    assert loaded.effective_settings()["llm_provider"] == "openai"


@pytest.mark.unit
def test_failure_block_is_allowlisted_and_safe():
    """REQ-TA-QR-001 (D-C/D-E): only {code, phase, diagnostic, exception_type?}."""
    block = build_failure(FailureCode.PROVIDER_TIMEOUT, phase="run",
                          exception_type="TimeoutError")
    assert set(block) <= {"code", "phase", "diagnostic", "exception_type"}
    assert block["code"] == "PROVIDER_TIMEOUT"
    text = json.dumps(block).lower()
    for forbidden in ("http", "://", "api_key", "/home/", "c:\\"):
        assert forbidden not in text
