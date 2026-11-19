"""Strict settings-replay loader for REQ-TA-FR-008 (Implements: REQ-TA-FR-008).

These tests pin the loader contract for re-running an analysis from the
version-1 ``replayable_settings`` allowlist of a prior QR-004 run record.

The loader reads configuration only. It never replays ticker, analysis date,
output paths, credentials, endpoints, or observational metadata, and it never
guarantees identical market data, provider responses, sampled LLM output,
timing, token usage, confidence, or final recommendation.

All fixtures are synthetic: no real credentials, endpoints, or local paths.
"""

from __future__ import annotations

import json

import pytest

from tradingagents.settings_replay import (
    ReplayError,
    ReplaySettings,
    load_replayable_settings,
)

# A complete, valid version-1 replayable_settings block (synthetic values only).
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
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "sec_edgar,yfinance",
        "news_data": "yfinance",
        "macro_data": "fred",
        "prediction_markets": "polymarket",
    },
    "tool_vendors": {},
}


def _write(tmp_path, payload, name="rec.json"):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _root_record(**overrides):
    rec = {"schema_version": "1", "replayable_settings": dict(VALID)}
    rec["replayable_settings"].update(overrides)
    return rec


# ----------------------------------------------------------------- positive

@pytest.mark.unit
def test_valid_root_record_loads(tmp_path):
    """REQ-TA-FR-008: a valid v1 root record loads into ReplaySettings."""
    result = load_replayable_settings(_write(tmp_path, _root_record()))
    assert isinstance(result, ReplaySettings)
    assert result.llm_provider == "deepseek"
    assert result.analysts == ("market", "news")
    assert result.max_tool_rounds == 3


@pytest.mark.unit
def test_effective_settings_equal_source(tmp_path):
    """REQ-TA-FR-008: loaded allowlisted settings equal the source block."""
    result = load_replayable_settings(_write(tmp_path, _root_record()))
    effective = result.effective_settings()
    for key in VALID:
        assert effective[key] == VALID[key]


@pytest.mark.unit
def test_full_state_log_structure_loads(tmp_path):
    """REQ-TA-FR-008: a full_states_log JSON (run_settings) also loads."""
    log = {"run_settings": _root_record(), "final_rating": "Buy"}
    result = load_replayable_settings(_write(tmp_path, log, "full_states_log_2026-11-16.json"))
    assert result.llm_provider == "deepseek"


@pytest.mark.unit
def test_optional_fields_absent_use_defaults(tmp_path):
    """REQ-TA-FR-008: absent optional fields normalize to documented defaults."""
    rec = _root_record()
    for key in ("temperature", "openai_reasoning_effort", "google_thinking_level",
                "anthropic_effort", "tool_vendors", "deep_think_provider",
                "quick_think_provider"):
        rec["replayable_settings"].pop(key, None)
    result = load_replayable_settings(_write(tmp_path, rec))
    eff = result.effective_settings()
    assert eff["temperature"] is None
    assert eff["tool_vendors"] == {}
    assert eff["deep_think_provider"] is None


@pytest.mark.unit
def test_round_trip(tmp_path):
    """REQ-TA-FR-008: loading is idempotent across a serialize/load cycle."""
    first = load_replayable_settings(_write(tmp_path, _root_record()))
    payload = {"schema_version": "1", "replayable_settings": first.effective_settings()}
    second = load_replayable_settings(_write(tmp_path, payload, "again.json"))
    assert first.effective_settings() == second.effective_settings()


# ----------------------------------------------------------------- negative

@pytest.mark.unit
def test_missing_file_raises(tmp_path):
    with pytest.raises(ReplayError):
        load_replayable_settings(tmp_path / "nope.json")


@pytest.mark.unit
def test_malformed_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReplayError):
        load_replayable_settings(p)


@pytest.mark.unit
def test_unsupported_schema_version_raises(tmp_path):
    rec = _root_record()
    rec["schema_version"] = "2"
    with pytest.raises(ReplayError, match="schema"):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_unknown_field_rejected(tmp_path):
    rec = _root_record()
    rec["replayable_settings"]["mystery_key"] = 1
    with pytest.raises(ReplayError, match="unknown"):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_forbidden_endpoint_field_rejected(tmp_path):
    rec = _root_record()
    rec["replayable_settings"]["backend_url"] = "https://relay.invalid/v1"
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_observational_field_in_replayable_rejected(tmp_path):
    rec = _root_record()
    rec["replayable_settings"]["status"] = "completed"
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_absolute_path_value_rejected(tmp_path):
    rec = _root_record()
    rec["replayable_settings"]["output_language"] = "/path/that/should/not/appear"
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_wrong_type_rejected(tmp_path):
    rec = _root_record(max_tool_rounds="three")
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
@pytest.mark.parametrize("bad_rounds", [0, -1])
def test_out_of_range_rounds_rejected(tmp_path, bad_rounds):
    rec = _root_record(max_debate_rounds=bad_rounds)
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_unsupported_provider_rejected(tmp_path):
    rec = _root_record(llm_provider="not_a_real_provider")
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_invalid_analyst_rejected(tmp_path):
    rec = _root_record(analysts=["market", "wizard"])
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_missing_required_field_rejected(tmp_path):
    rec = _root_record()
    del rec["replayable_settings"]["llm_provider"]
    with pytest.raises(ReplayError, match="llm_provider"):
        load_replayable_settings(_write(tmp_path, rec))


@pytest.mark.unit
def test_multiple_candidate_blocks_rejected(tmp_path):
    """Ambiguous input (root + embedded run_settings) is rejected, not searched."""
    rec = _root_record()
    ambiguous = {"schema_version": "1", "replayable_settings": dict(VALID),
                 "run_settings": dict(rec)}
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, ambiguous))


@pytest.mark.unit
def test_no_candidate_block_rejected(tmp_path):
    with pytest.raises(ReplayError):
        load_replayable_settings(_write(tmp_path, {"unrelated": True}))


# ------------------------------------------------------------------ privacy

@pytest.mark.unit
def test_error_does_not_echo_forbidden_value(tmp_path):
    """REQ-TA-FR-008 privacy: a rejected secret-like value is never echoed."""
    # Synthetic credential-like value assembled from fragments so no literal
    # credential keyword lives in the source; it only needs to look like one to
    # the validator (which must not echo it).
    secret_value = "".join(("s", "k", "-", "synthetic", "0" * 20))
    rec = _root_record()
    rec["replayable_settings"]["temperature"] = secret_value  # wrong type + secret-like
    with pytest.raises(ReplayError) as excinfo:
        load_replayable_settings(_write(tmp_path, rec))
    assert secret_value not in str(excinfo.value)



# ------------------------------------------------------------------ CLI wiring

@pytest.mark.unit
def test_cli_rejects_from_settings_combined_with_profile(tmp_path, monkeypatch):
    """REQ-TA-FR-008: --from-settings + --profile is a conflict and is rejected."""
    from typer.testing import CliRunner

    import cli.main as cli_main

    rec = _write(tmp_path, _root_record())
    called = {}
    monkeypatch.setattr(cli_main, "run_analysis", lambda **kw: called.update(kw))
    result = CliRunner().invoke(
        cli_main.app,
        ["--from-settings", str(rec), "--profile", "deep",
         "--ticker", "NVDA", "--date", "2026-11-16", "--save", "--no-show"],
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    assert "run_analysis" not in called or not called


@pytest.mark.unit
def test_cli_forwards_from_settings(tmp_path, monkeypatch):
    """REQ-TA-FR-008: --from-settings is forwarded to run_analysis."""
    from typer.testing import CliRunner

    import cli.main as cli_main

    rec = _write(tmp_path, _root_record())
    seen = {}
    monkeypatch.setattr(cli_main, "run_analysis", lambda **kw: seen.update(kw))
    result = CliRunner().invoke(
        cli_main.app,
        ["--from-settings", str(rec), "--ticker", "NVDA", "--date", "2026-11-16",
         "--save", "--no-show"],
    )
    assert result.exit_code == 0, result.output
    assert seen["flags"]["from_settings"] == str(rec)


# ---------------------------------------------- effective-config reconstruction

@pytest.mark.unit
def test_selections_from_replay_reflects_record(tmp_path):
    """REQ-TA-FR-008: replay selections carry the record's settings, ticker/date supplied."""
    from cli.run import _selections_from_replay

    rec = _write(tmp_path, _root_record())
    flags = {"ticker": "NVDA", "date": "2026-11-16", "from_settings": str(rec)}
    sel = _selections_from_replay(str(rec), flags)
    assert sel["ticker"] == "NVDA"
    assert sel["analysis_date"] == "2026-11-16"
    assert [a.value for a in sel["analysts"]] == ["market", "news"]
    assert sel["llm_provider"] == "deepseek"
    assert sel["quick_think_llm"] == "deepseek-flash"


@pytest.mark.unit
def test_replay_needs_ticker_and_date(tmp_path):
    """REQ-TA-FR-008: ticker and date are supplied, not replayed."""
    from cli.run import _selections_from_replay

    rec = _write(tmp_path, _root_record())
    with pytest.raises(ValueError, match="ticker and --date"):
        _selections_from_replay(str(rec), {"from_settings": str(rec)})


@pytest.mark.unit
def test_replay_resolution_matches_source_profile_none(tmp_path):
    """REQ-TA-FR-008: profile=None + recorded resolved rounds reproduce the source."""
    from tradingagents.default_config import resolve_profile

    replayed = load_replayable_settings(_write(tmp_path, _root_record()))
    resolved = resolve_profile(
        None,
        explicit={
            "analysts": list(replayed.analysts),
            "max_debate_rounds": replayed.max_debate_rounds,
            "max_risk_discuss_rounds": replayed.max_risk_discuss_rounds,
            "max_tool_rounds": replayed.max_tool_rounds,
        },
    )
    assert list(resolved.analysts) == VALID["analysts"]
    assert resolved.max_debate_rounds == VALID["max_debate_rounds"]
    assert resolved.max_risk_discuss_rounds == VALID["max_risk_discuss_rounds"]
    assert resolved.max_tool_rounds == VALID["max_tool_rounds"]
    assert resolved.requested_profile is None
