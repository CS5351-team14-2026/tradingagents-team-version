"""REQ-TA-FR-002 configuration and CLI inputs, without external services."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from rich.text import Text
from typer.testing import CliRunner

import cli.main as cli_main
import cli.run as cli_run
import tradingagents.default_config as default_config
from cli.models import AnalystType
from tradingagents.graph import trading_graph


def _config(monkeypatch, raw=None):
    for name in default_config._ENV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    if raw is not None:
        monkeypatch.setenv("TRADINGAGENTS_TOKEN_BUDGET", raw)
    return default_config.build_default_config()


@pytest.fixture(params=[False, True], ids=["plain", "ansi"])
def budget_cli_output(monkeypatch, request):
    """REQ-TA-FR-002: exercise real CLI rendering with and without ANSI styles."""
    output = StringIO()

    def make_console(*args, **kwargs):
        kwargs.update(file=output, force_terminal=request.param, legacy_windows=False,
                      color_system="standard" if request.param else None, width=120)
        return Console(*args, **kwargs)

    monkeypatch.setattr("typer.rich_utils.Console", make_console)
    return output, request.param


@pytest.mark.unit
@pytest.mark.parametrize("raw", [None, ""], ids=["unset", "blank"])
def test_req_fr002_budget_disabled_by_default(monkeypatch, raw):
    assert _config(monkeypatch, raw)["token_budget"] is None


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [("0", 0), ("1", 1), (" 1500 ", 1500)])
def test_req_fr002_environment_budget_is_nonnegative_integer(monkeypatch, raw, expected):
    config = _config(monkeypatch, raw)

    assert config["token_budget"] == expected
    assert type(config["token_budget"]) is int
    assert config["max_tokens"] is None


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["-1", "1.5", "true", "False", "None", " ", "1e3", "100 tokens"])
def test_req_fr002_invalid_environment_budget_is_rejected(monkeypatch, raw):
    with pytest.raises(ValueError, match="TRADINGAGENTS_TOKEN_BUDGET"):
        _config(monkeypatch, raw)


@pytest.mark.unit
def test_req_fr002_budget_is_independent_of_output_cap_and_profile(monkeypatch):
    _config(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TOKEN_BUDGET", "123")
    monkeypatch.setenv("TRADINGAGENTS_MAX_TOKENS", "50")
    config = default_config.build_default_config()

    assert config["token_budget"] == 123
    assert config["max_tokens"] == "50"  # Preserve the existing per-call cap contract.
    for profile in default_config.PROFILE_MAPPING.values():
        assert "token_budget" not in profile


@pytest.mark.unit
@pytest.mark.parametrize("budget", [0, 5])
def test_req_fr002_cli_explicit_budget_reaches_run_separately_from_flags(monkeypatch, budget):
    calls = []
    monkeypatch.setenv("TRADINGAGENTS_TOKEN_BUDGET", "100")
    monkeypatch.setattr(cli_main, "run_analysis", lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(cli_main.app, ["--token-budget", str(budget), "--ticker", "NVDA"])

    assert result.exit_code == 0, result.output
    assert calls[0]["token_budget"] == budget
    assert "token_budget" not in calls[0]["flags"]
    assert calls[0]["flags"]["ticker"] == "NVDA"


@pytest.mark.unit
def test_req_fr002_cli_omitted_budget_preserves_existing_run_and_flags_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_main, "run_analysis", lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(cli_main.app, [])

    assert result.exit_code == 0, result.output
    assert calls == [{
        "checkpoint": None,
        "portfolio": None,
        "flags": {"ticker": None, "date": None, "analysts": None, "save": None, "show": None, "html": None},
        "profile": None,
    }]


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["-1", "1.5", "true"])
def test_req_fr002_cli_invalid_budget_stops_before_analysis(monkeypatch, raw, budget_cli_output):
    monkeypatch.setattr(cli_main, "run_analysis", lambda **kwargs: pytest.fail("analysis started"))

    result = CliRunner().invoke(cli_main.app, ["--token-budget", raw])

    stream, ansi = budget_cli_output
    output = result.output + stream.getvalue()
    assert ("\x1b[" in output) == ansi
    assert result.exit_code != 0
    assert "--token-budget" in Text.from_ansi(output).plain


@pytest.mark.unit
def test_req_fr002_cli_help_explains_budget_can_be_exceeded(budget_cli_output):
    result = CliRunner().invoke(cli_main.app, ["--help"])

    stream, ansi = budget_cli_output
    output = result.output + stream.getvalue()
    assert ("\x1b[" in output) == ansi
    assert result.exit_code == 0
    text = " ".join(Text.from_ansi(output).plain.split())
    assert "--token-budget" in text
    assert "required" in text and "exceed" in text


class _ConfigurationCaptured(Exception):
    """Stop after real CLI configuration resolution, before graph/provider setup."""


@pytest.mark.unit
@pytest.mark.parametrize("env_budget,flag_budget,expected", [
    (None, None, None),
    ("100", None, 100),
    ("100", "50", 50),
    ("100", "0", 0),
    (None, "0", 0),
])
@pytest.mark.parametrize("profile", [None, "deep"], ids=["baseline", "profile"])
def test_req_fr002_real_cli_config_flag_wins_over_environment(
        monkeypatch, env_budget, flag_budget, expected, profile):
    config = _config(monkeypatch, env_budget)
    monkeypatch.delenv("TRADINGAGENTS_PROFILE", raising=False)
    monkeypatch.setattr(cli_run, "DEFAULT_CONFIG", config)
    monkeypatch.setattr(cli_run, "unattended_gaps", lambda flags: [])
    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags: {
        "ticker": "NVDA", "analysis_date": "2026-01-09", "asset_type": "stock",
        "analysts": [AnalystType.MARKET], "research_depth": 1,
        "quick_think_llm": "offline-quick", "deep_think_llm": "offline-deep",
        "backend_url": None, "llm_provider": "openai", "output_language": "English",
    })
    captured = []

    def capture(**kwargs):
        captured.append(kwargs)
        raise _ConfigurationCaptured

    monkeypatch.setattr(cli_run, "TradingAgentsGraph", capture)
    args = ["--ticker", "NVDA", "--no-save", "--no-show"]
    if flag_budget is not None:
        args += ["--token-budget", flag_budget]
    if profile is not None:
        args += ["--profile", profile]

    result = CliRunner().invoke(cli_main.app, args)

    assert isinstance(result.exception, _ConfigurationCaptured), result.output
    assert captured[0]["config"]["token_budget"] == expected
    assert captured[0]["callbacks"][0].tracker.limit == expected
    assert captured[0]["config"]["max_tokens"] is None


@pytest.mark.unit
@pytest.mark.parametrize("invalid", [-1, True, False, 1.5, "100", [], {}])
def test_req_fr002_graph_rejects_invalid_budget_before_provider_or_files(
        monkeypatch, tmp_path, invalid):
    def provider(*args, **kwargs):
        pytest.fail("provider constructed for an invalid budget")

    monkeypatch.setattr(trading_graph, "create_tier_client", provider)
    config = dict(default_config.DEFAULT_CONFIG, token_budget=invalid,
                  results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"))

    with pytest.raises(ValueError, match="token budget"):
        trading_graph.TradingAgentsGraph(config=config)

    assert not (tmp_path / "results").exists()
    assert not (tmp_path / "cache").exists()
