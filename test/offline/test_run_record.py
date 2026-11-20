"""Canonical run record: structure, usage, status and safety (REQ-TA-QR-004).

These are offline, deterministic tests of the run record itself and of the flat
``run_settings()`` view that now carries it. They assert the QR-004 contract:
one canonical structured record with a schema version, a ``replayable_settings``
section separated from an observational ``run_metadata`` section, unavailable
usage represented as null with ``usage_complete=false``, a fixed status
vocabulary, deterministic serialization, and no secret or local-path leakage.
"""

from __future__ import annotations

import json

import pytest

from tradingagents import run_record as record
from tradingagents.graph.trading_graph import TradingAgentsGraph


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
        **config_overrides,
    }
    return graph


# ---------------------------------------------------------------- structure

@pytest.mark.unit
def test_record_has_schema_version_and_two_canonical_sections():
    """REQ-TA-QR-004: the record exposes a schema version and the two separated sections."""
    settings = _bare_graph().run_settings()
    assert settings["schema_version"] == record.RECORD_SCHEMA_VERSION
    assert isinstance(settings["replayable_settings"], dict)
    assert isinstance(settings["run_metadata"], dict)


@pytest.mark.unit
def test_replayable_and_observational_fields_do_not_mix():
    """REQ-TA-QR-004: token/status observational fields never appear in replayable_settings."""
    settings = _bare_graph().run_settings()
    replayable = settings["replayable_settings"]
    for observational in ("status", "tokens_in", "tokens_out", "total_tokens",
                          "llm_calls", "tool_calls", "usage_complete", "started_at",
                          "completed_at", "version"):
        assert observational not in replayable


@pytest.mark.unit
def test_required_replayable_fields_present():
    """REQ-TA-QR-004: every required replayable setting is present and typed."""
    replayable = _bare_graph().run_settings()["replayable_settings"]
    for key in ("profile", "analysts", "llm_provider", "deep_think_llm",
                "quick_think_llm", "max_debate_rounds", "max_risk_discuss_rounds",
                "max_tool_rounds", "output_language", "data_vendors", "tool_vendors"):
        assert key in replayable
    assert isinstance(replayable["analysts"], list)
    assert isinstance(replayable["max_debate_rounds"], int)


@pytest.mark.unit
def test_profile_may_be_null_and_is_not_invented():
    """A1: profile records the actual requested value; null when none requested."""
    replayable = _bare_graph().run_settings()["replayable_settings"]
    assert replayable["profile"] is None


# --------------------------------------------------------------------- usage

@pytest.mark.unit
def test_usage_complete_is_aggregated_into_metadata():
    """REQ-TA-QR-004: complete provider usage is summed into the run metadata."""
    graph = _bare_graph()
    graph.set_run_observations(
        usage=record.build_usage_summary(
            {"tokens_in": 120, "tokens_out": 80, "llm_calls": 5, "tool_calls": 2}
        )
    )
    meta = graph.run_settings()["run_metadata"]
    assert meta["usage_complete"] is True
    assert meta["tokens_in"] == 120
    assert meta["tokens_out"] == 80
    assert meta["total_tokens"] == 200
    assert meta["llm_calls"] == 5
    assert meta["tool_calls"] == 2


@pytest.mark.unit
def test_unavailable_usage_is_null_with_incomplete_flag():
    """A3: unavailable usage is usage_complete=false with null token values (never 0)."""
    meta = _bare_graph().run_settings()["run_metadata"]
    assert meta["usage_complete"] is False
    assert meta["tokens_in"] is None
    assert meta["tokens_out"] is None
    assert meta["total_tokens"] is None


@pytest.mark.unit
def test_partial_usage_is_not_a_complete_total():
    """REQ-TA-QR-004: a partial usage report never yields a total."""
    summary = record.build_usage_summary({"tokens_in": 10, "tokens_out": None})
    assert summary.usage_complete is False
    assert summary.total_tokens is None


# -------------------------------------------------------------------- status

@pytest.mark.unit
def test_status_defaults_to_completed():
    """A2: status uses the existing vocabulary; a finished run is completed."""
    assert _bare_graph().run_settings()["run_metadata"]["status"] == record.STATUS_COMPLETED


@pytest.mark.unit
def test_status_failed_is_recorded_on_controlled_failure():
    """A2: a controlled failure records status=failed (no invented status)."""
    graph = _bare_graph()
    graph.set_run_observations(status=record.STATUS_FAILED)
    assert graph.run_settings()["run_metadata"]["status"] == record.STATUS_FAILED


@pytest.mark.unit
def test_unknown_status_is_rejected():
    """A2: the record refuses a status outside the approved vocabulary."""
    graph = _bare_graph()
    graph.set_run_observations(status="exploded")
    with pytest.raises(ValueError, match="status must be one of"):
        graph.run_settings()


# ----------------------------------------------------------- serialization

@pytest.mark.unit
def test_serialization_is_deterministic_and_json_safe():
    """REQ-TA-QR-004: the record serializes to stable JSON."""
    settings = _bare_graph().run_settings()
    first = json.dumps(settings, sort_keys=True)
    second = json.dumps(_bare_graph().run_settings(), sort_keys=True)
    assert first == second
    # Round-trips through JSON without error.
    assert json.loads(first)["schema_version"] == record.RECORD_SCHEMA_VERSION


# ------------------------------------------------------------------ safety

@pytest.mark.unit
def test_no_secret_or_local_path_in_record():
    """REQ-TA-QR-004: endpoints, credentials and local paths never reach the record.

    The fake endpoint and path below are placeholders: they exist only to prove
    the allowlist drops them, and are not real credentials or real home paths.
    """
    graph = _bare_graph(backend_url="https://relay.invalid/v1",
                        results_dir="/path/that/should/not/appear")
    settings = graph.run_settings()
    text = json.dumps(settings)
    assert "secret" not in text
    assert "/path/that/should/not/appear" not in text
    assert "relay.invalid" not in text


@pytest.mark.unit
def test_legacy_flat_keys_are_preserved():
    """Migration C: existing flat consumers keep reading the same keys."""
    settings = _bare_graph().run_settings()
    assert settings["analysts"] == ["market", "news"]
    assert settings["llm_provider"] == "openai"
    assert settings["max_debate_rounds"] == 1
    assert settings["version"]


# ------------------------------------------------------------ report header

@pytest.mark.unit
def test_report_header_shows_status_and_complete_tokens():
    """REQ-TA-QR-004: the report header renders run status and token totals."""
    from tradingagents.reporting import _header

    graph = _bare_graph()
    graph.set_run_observations(
        usage=record.build_usage_summary(
            {"tokens_in": 120, "tokens_out": 80, "llm_calls": 5, "tool_calls": 2}
        )
    )
    header = _header("NVDA", {"trade_date": "2026-01-09"}, graph.run_settings())
    assert "Run status: completed" in header
    assert "Tokens: 120 in, 80 out, 200 total" in header


@pytest.mark.unit
def test_report_header_shows_unavailable_when_usage_incomplete():
    """A3: incomplete usage renders as "unavailable", never as a fabricated zero."""
    from tradingagents.reporting import _header

    header = _header("NVDA", {"trade_date": "2026-01-09"}, _bare_graph().run_settings())
    assert "Tokens: unavailable" in header


# --------------------------------------------------------- failure paths
#
# REQ-TA-QR-004: every terminal run path records structured metadata. These
# tests pin the failure-path behaviour: a failed run records status=failed and
# a standalone record on disk, a successful run records status=completed, and
# the persisted record carries the final observations rather than the
# pre-observation defaults.

import functools  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402


def _minimal_graph(tmp_path):
    """A graph bound to the real settings/record methods, with a temp results dir."""
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
        "results_dir": str(tmp_path),
    }
    return graph


def _record_path(tmp_path, ticker="NVDA", date="2026-01-09"):
    return tmp_path / ticker / "TradingAgentsStrategy_logs" / f"run_record_{date}.json"


@pytest.mark.unit
def test_write_run_record_persists_failed_status(tmp_path):
    """REQ-TA-QR-004: a failed run writes a record whose status is failed."""
    graph = _minimal_graph(tmp_path)
    graph.set_run_observations(status=record.STATUS_FAILED,
                               completed_at="2026-01-09T10:00:00+00:00")
    path = graph.write_run_record("NVDA", "2026-01-09")
    assert path == _record_path(tmp_path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["run_metadata"]["status"] == record.STATUS_FAILED
    assert on_disk["schema_version"] == record.RECORD_SCHEMA_VERSION


@pytest.mark.unit
def test_write_run_record_has_no_secret_or_path(tmp_path):
    """REQ-TA-QR-004: the persisted record carries no endpoint, key or local path."""
    graph = _minimal_graph(tmp_path)
    graph.set_run_observations(status=record.STATUS_FAILED)
    path = graph.write_run_record("NVDA", "2026-01-09")
    text = path.read_text(encoding="utf-8")
    assert "secret" not in text and "api_key" not in text
    assert str(tmp_path) not in text


@pytest.mark.unit
def test_run_graph_records_failed_and_reraises_on_exception(tmp_path):
    """REQ-TA-QR-004: _run_graph stamps failed, writes a record, and re-raises."""
    graph = MagicMock()
    graph.debug = False
    graph.config = _minimal_graph(tmp_path).config
    graph.profile_resolution = None
    graph._run_usage = None
    graph._run_status = None
    graph._run_started_at = None
    graph._run_completed_at = None
    graph.create_run_state.return_value = {"company_of_interest": "NVDA"}
    graph.checkpoint_input.return_value = {}
    graph.propagator.get_graph_args.return_value = {}
    graph.graph.invoke.side_effect = RuntimeError("boom")
    # Bind the real methods whose behaviour we assert.
    graph.set_run_observations = functools.partial(
        TradingAgentsGraph.set_run_observations, graph)
    graph.write_run_record = functools.partial(TradingAgentsGraph.write_run_record, graph)
    graph.run_settings = functools.partial(TradingAgentsGraph.run_settings, graph)

    with pytest.raises(RuntimeError, match="boom"):
        TradingAgentsGraph._run_graph(graph, "NVDA", "2026-01-09")

    on_disk = json.loads(_record_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk["run_metadata"]["status"] == record.STATUS_FAILED


@pytest.mark.unit
def test_run_graph_records_completed_on_success(tmp_path):
    """REQ-TA-QR-004: a successful _run_graph records status=completed."""
    graph = MagicMock()
    graph.debug = False
    graph.config = _minimal_graph(tmp_path).config
    graph.profile_resolution = None
    graph._run_usage = None
    graph._run_status = None
    graph._run_started_at = None
    graph._run_completed_at = None
    graph.create_run_state.return_value = {"company_of_interest": "NVDA"}
    graph.checkpoint_input.return_value = {}
    graph.propagator.get_graph_args.return_value = {}
    graph.graph.invoke.return_value = {"final_trade_decision": "Buy"}
    # record_decision/clear_checkpoint are no-ops for this unit test.
    graph.record_decision = MagicMock()
    graph.clear_checkpoint_on_success = MagicMock()
    graph.set_run_observations = functools.partial(
        TradingAgentsGraph.set_run_observations, graph)
    graph.run_settings = functools.partial(TradingAgentsGraph.run_settings, graph)

    TradingAgentsGraph._run_graph(graph, "NVDA", "2026-01-09")

    # The observations were set before record_decision, so the graph's own record
    # carries completed status.
    assert graph._run_status == record.STATUS_COMPLETED


@pytest.mark.unit
def test_persisted_record_carries_final_observations_not_defaults(tmp_path):
    """REQ-TA-QR-004: status is stamped before persistence, not left at default."""
    graph = MagicMock()
    graph.debug = False
    graph.config = _minimal_graph(tmp_path).config
    graph.profile_resolution = None
    graph._run_usage = None
    graph._run_status = None
    graph._run_started_at = None
    graph._run_completed_at = None
    graph.create_run_state.return_value = {"company_of_interest": "NVDA"}
    graph.checkpoint_input.return_value = {}
    graph.propagator.get_graph_args.return_value = {}
    graph.graph.invoke.return_value = {"final_trade_decision": "Buy"}
    graph.clear_checkpoint_on_success = MagicMock()
    graph.set_run_observations = functools.partial(
        TradingAgentsGraph.set_run_observations, graph)
    graph.run_settings = functools.partial(TradingAgentsGraph.run_settings, graph)

    seen = {}
    def _capture_record(company, date, final_state):
        seen["record"] = graph.run_settings()
    graph.record_decision = _capture_record

    TradingAgentsGraph._run_graph(graph, "NVDA", "2026-01-09")

    meta = seen["record"]["run_metadata"]
    assert meta["status"] == record.STATUS_COMPLETED
    assert meta["completed_at"] is not None
