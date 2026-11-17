"""Budget record/report compatibility (REQ-TA-FR-002/QR-004/QR-005; ADR-003)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tradingagents import run_record
from tradingagents.reporting import write_report_tree
from tradingagents.run_budget import (
    BUDGET_EXHAUSTED,
    BUDGET_OK,
    BUDGET_WARNING,
    CallRole,
    RunBudgetTracker,
    UsageObservation,
)

from .test_reporting import SETTINGS, _state


def _snapshot(limit=10, observation=None):
    tracker = RunBudgetTracker(limit)
    tracker.start_call("call", "analysis")
    tracker.finish_call("call", observation or UsageObservation(3, 2, 5, "complete"))
    return tracker


def _record(snapshot=None, status="completed", usage=None):
    return run_record.build_run_record(
        replayable_settings={"analysts": ["market"]},
        usage=usage,
        budget=snapshot,
        status=status,
        legacy=SETTINGS,
    ).to_dict()


@pytest.mark.unit
@pytest.mark.parametrize("limit,observation,status,reason", [
    (10, UsageObservation(3, 2, 5, "complete"), BUDGET_OK, "WITHIN_RECORDED_BUDGET"),
    (5, UsageObservation(3, 2, 5, "complete"), BUDGET_EXHAUSTED, "RECORDED_USAGE_REACHED_LIMIT"),
    (4, UsageObservation(3, 2, 5, "complete"), BUDGET_EXHAUSTED, "RECORDED_USAGE_EXCEEDED_LIMIT"),
    (10, UsageObservation(3, None, None, "partial"), BUDGET_WARNING, "USAGE_PARTIAL"),
    (10, UsageObservation(), BUDGET_WARNING, "USAGE_UNAVAILABLE"),
    (10, UsageObservation(3, 2, None, "conflict"), BUDGET_WARNING, "USAGE_CONFLICT"),
])
def test_fr002_budget_results_and_reasons_are_machine_readable_without_changing_status(
        limit, observation, status, reason):
    """REQ-TA-FR-002/QR-004: statuses are independent and JSON preserves unknown values."""
    tracker = _snapshot(limit, observation)
    if status != BUDGET_OK:
        tracker.try_start(call_id="next", phase="research", role=CallRole.OPTIONAL)
    result = _record(tracker.snapshot(), status="failed")
    saved = json.loads(json.dumps(result))
    budget = saved["run_metadata"]["budget"]

    assert saved["schema_version"] == "2"
    assert saved["run_metadata"]["status"] == "failed"
    assert budget["status"] == status
    assert budget["reason_codes"] == [reason]
    assert budget["limit"] == limit
    assert budget["enforcement_enabled"] is True
    assert budget["blocked_calls"] == (0 if status == BUDGET_OK else 1)
    assert budget["usage_state"] == observation.state
    assert budget["known_tokens"] == observation.known_tokens
    if observation.state != "complete":
        assert saved["run_metadata"]["total_tokens"] is None
        assert saved["run_metadata"]["usage_complete"] is False
    assert set(budget) == {"limit", "enforcement_enabled", "status", "reason_codes",
                           "known_tokens", "usage_state", "blocked_calls"}
    assert "call" not in budget
    assert "budget" not in saved["replayable_settings"]


@pytest.mark.unit
def test_fr002_schema_two_keeps_legacy_keys_and_observations_out_of_replay_settings():
    """REQ-TA-FR-002/QR-004: additive migration retains flat consumers and safe replay inputs."""
    replayable = {"analysts": ["market"], "token_budget": 10}
    snapshot = _snapshot().snapshot()
    result = run_record.build_run_record(
        replayable_settings=replayable, budget=snapshot, legacy=SETTINGS,
    ).to_dict()
    assert result["replayable_settings"] == replayable
    assert all(result[key] == value for key, value in SETTINGS.items())
    assert "known_tokens" not in result["replayable_settings"]
    assert "reason_codes" not in result["replayable_settings"]
    assert "run_id" not in result["run_metadata"]["budget"]


@pytest.mark.unit
@pytest.mark.parametrize("usage,known,state", [
    (None, None, "unavailable"),
    (run_record.UsageSummary(tokens_in=3), 3, "partial"),
    (run_record.UsageSummary(tokens_in=0, tokens_out=0, usage_complete=True), 0, "complete"),
])
def test_fr002_no_budget_records_disabled_without_inventing_zero_or_replay_input(usage, known, state):
    """REQ-TA-FR-002/QR-004: no configured budget preserves honest unavailable versus zero."""
    result = _record(usage=usage)
    budget = result["run_metadata"]["budget"]
    assert budget["status"] == BUDGET_OK
    assert budget["reason_codes"] == ["NOT_CONFIGURED"]
    assert budget["limit"] is None and budget["enforcement_enabled"] is False
    assert budget["known_tokens"] == known
    assert budget["usage_state"] == state
    assert "token_budget" not in result["replayable_settings"]


@pytest.mark.unit
def test_fr002_unconfigured_snapshot_keeps_missing_usage_explicit():
    """REQ-TA-FR-002: disabled enforcement is independent of unavailable measured usage."""
    result = _record(_snapshot(None, UsageObservation()).snapshot())
    budget = result["run_metadata"]["budget"]
    assert budget["status"] == BUDGET_OK
    assert budget["reason_codes"] == ["NOT_CONFIGURED"]
    assert budget["usage_state"] == "unavailable"
    assert budget["known_tokens"] is None
    assert result["run_metadata"]["total_tokens"] is None


@pytest.mark.unit
def test_fr002_serializer_preserves_tracker_recovery_diagnostics():
    """REQ-TA-FR-002/QR-004: metadata does not replace recovery reasons with guessed policy."""
    reasons = ("BUDGET_HISTORY_UNAVAILABLE", "BUDGET_LEDGER_INVALID", "BUDGET_PERSISTENCE_FAILED")
    snapshot = replace(_snapshot().snapshot(), status=BUDGET_WARNING, reason_codes=reasons)
    assert _record(snapshot)["run_metadata"]["budget"]["reason_codes"] == list(reasons)


@pytest.mark.unit
def test_fr002_budget_status_cannot_be_used_as_lifecycle_status():
    """REQ-TA-FR-002/QR-004: the existing completed/failed vocabulary remains closed."""
    with pytest.raises(ValueError, match="run status must be one of"):
        _record(_snapshot(0).snapshot(), status=BUDGET_EXHAUSTED)


@pytest.mark.unit
@pytest.mark.parametrize("observation,expected_status,known_text", [
    (UsageObservation(3, 2, 5, "complete"), BUDGET_OK, "5"),
    (UsageObservation(3, None, None, "partial"), BUDGET_WARNING, "3"),
    (UsageObservation(), BUDGET_WARNING, "unavailable"),
])
def test_fr002_markdown_and_html_report_same_observed_budget_and_unknown_usage(
        tmp_path, observation, expected_status, known_text):
    """REQ-TA-FR-002/QR-004/QR-005: both offline reports show the same honest budget result."""
    snapshot = _snapshot(10, observation).snapshot()
    settings = _record(snapshot)
    write_report_tree(_state(), "NVDA", tmp_path, settings=settings)
    markdown = (tmp_path / "complete_report.md").read_text(encoding="utf-8")
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert f"Token budget: {expected_status}" in markdown
    assert f"Known tokens (observed): {known_text}" in markdown
    assert "Usage completeness: " + observation.state in markdown
    for text in (expected_status, snapshot.reason_codes[0], known_text, observation.state,
                 "Already started and required calls can exceed the limit", "not a hard cap"):
        assert text in markdown
        assert text in page
    if observation.state != "complete":
        assert "Tokens: unavailable" in markdown
        assert "<dt>Tokens</dt><dd>unavailable</dd>" in page


@pytest.mark.unit
def test_fr002_exhausted_diagnostic_report_retains_failed_review_and_reason(tmp_path):
    """REQ-TA-FR-002/QR-001/QR-004/INV-001: exhaustion diagnostics cannot present a normal recommendation."""
    settings = _record(_snapshot(4).snapshot(), status="failed")
    state = {"trade_date": "2026-01-09", "final_rating": "REVIEW",
             "final_trade_decision": "**Rating**: REVIEW\n\nNo valid recommendation; token budget stopped retry.",
             "budget_termination": {"phase": "portfolio", "reason_codes": ["RECORDED_USAGE_EXCEEDED_LIMIT"]}}
    write_report_tree(state, "NVDA", tmp_path, settings=settings)
    markdown = (tmp_path / "complete_report.md").read_text(encoding="utf-8")
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    for text in ("failed", "REVIEW", BUDGET_EXHAUSTED, "RECORDED_USAGE_EXCEEDED_LIMIT",
                 "No valid recommendation"):
        assert text in markdown and text in page
    assert "Run status: failed" in markdown
    assert "<dt>Run status</dt><dd>failed</dd>" in page


@pytest.mark.unit
def test_fr002_no_budget_reports_disabled_without_claiming_enforcement(tmp_path):
    """REQ-TA-FR-002: NOT_CONFIGURED is visible rather than an apparent enforced allowance."""
    write_report_tree(_state(), "NVDA", tmp_path, settings=_record())
    markdown = (tmp_path / "complete_report.md").read_text(encoding="utf-8")
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert "Budget enforcement: disabled" in markdown
    assert "<dt>Budget enforcement</dt><dd>disabled</dd>" in page
    assert "NOT_CONFIGURED" in markdown and "NOT_CONFIGURED" in page
    assert "Stops new optional LLM calls" not in markdown
    assert "Stops new optional LLM calls" not in page


@pytest.mark.unit
def test_fr002_schema_one_report_inputs_remain_supported_without_budget_claims(tmp_path):
    """REQ-TA-FR-002/QR-004: old records render without fabricating a historical budget."""
    settings = {**SETTINGS, "schema_version": "1",
                "run_metadata": {"status": "completed", "usage_complete": False}}
    write_report_tree(_state(), "NVDA", tmp_path, settings=settings)
    markdown = (tmp_path / "complete_report.md").read_text(encoding="utf-8")
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert "Token budget" not in markdown and "Token budget" not in page
    assert "Tokens: unavailable" in markdown
    assert "<dt>Tokens</dt><dd>unavailable</dd>" in page


@pytest.mark.unit
def test_fr002_budget_metadata_is_escaped_in_html_report(tmp_path):
    """REQ-TA-FR-002/QR-004: report diagnostics remain text and cannot inject HTML."""
    settings = _record(_snapshot().snapshot())
    settings["run_metadata"]["budget"]["reason_codes"] = ["<script>not executable</script>"]
    write_report_tree(_state(), "NVDA", tmp_path, settings=settings)
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert "<script>not executable</script>" not in page
    assert "&lt;script&gt;not executable&lt;/script&gt;" in page
