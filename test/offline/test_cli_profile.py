"""The CLI selects and applies an analysis profile (REQ-TA-FR-001; ADR-002).

These tests drive the real CLI seams — ``requested_profile``, ``unattended_gaps``,
``_prompt_selections``, ``_build_run_config`` and ``run_analysis`` — offline, with
the graph replaced by a fake. They pin that ``--profile`` beats the environment,
an unknown profile fails before the gap check / prompts / model clients naming
the legal values, a selected profile skips the analyst and depth questions,
omitted mode keeps the original flow, and the execution plan, progress buffer and
graph all read one resolved config.
"""

from __future__ import annotations

import pytest
import typer

import cli.main as cli_main
import cli.run as cli_run
from cli import selections
from cli.models import AnalystType

FLAGS = {"ticker": "NVDA", "date": "2026-01-10", "analysts": None,
         "save": True, "show": False, "html": None}

UNATTENDED_ENV = {
    "TRADINGAGENTS_OUTPUT_LANGUAGE": "English",
    "TRADINGAGENTS_LLM_PROVIDER": "openai",
    "TRADINGAGENTS_QUICK_THINK_LLM": "gpt-6-luna",
}


def _clear_profile_env(monkeypatch):
    for name in ("TRADINGAGENTS_PROFILE", "TRADINGAGENTS_MAX_DEBATE_ROUNDS",
                 "TRADINGAGENTS_MAX_RISK_ROUNDS", "TRADINGAGENTS_MAX_TOOL_ROUNDS"):
        monkeypatch.delenv(name, raising=False)


# --- requested_profile ----------------------------------------------------------

@pytest.mark.unit
def test_profile_flag_beats_the_environment(monkeypatch):
    """REQ-TA-FR-001: --profile wins over TRADINGAGENTS_PROFILE."""
    monkeypatch.setenv("TRADINGAGENTS_PROFILE", "deep")
    assert selections.requested_profile({"profile": "quick"}) == "quick"


@pytest.mark.unit
def test_the_environment_profile_applies_without_a_flag(monkeypatch):
    """REQ-TA-FR-001: TRADINGAGENTS_PROFILE selects the profile when no flag is given."""
    monkeypatch.setenv("TRADINGAGENTS_PROFILE", "deep")
    assert selections.requested_profile({"profile": None}) == "deep"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["turbo", "QUICK", "deep "])
def test_an_unknown_profile_names_the_legal_values(monkeypatch, bad):
    """REQ-TA-FR-001: an invalid profile raises, listing quick, standard, deep."""
    _clear_profile_env(monkeypatch)
    with pytest.raises(ValueError) as caught:
        selections.requested_profile({"profile": bad})
    message = str(caught.value)
    for legal in ("quick", "standard", "deep"):
        assert legal in message


# --- unattended_gaps ------------------------------------------------------------

@pytest.mark.unit
def test_a_profile_supplies_analysts_and_rounds_so_they_are_not_gaps(monkeypatch, tmp_path):
    """REQ-TA-FR-001: with a profile, headless needs no --analysts or round env; the
    other required inputs are still checked."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)

    flags = {"ticker": "NVDA", "date": "2026-01-10", "analysts": None,
             "save": True, "show": False, "html": None, "profile": "quick"}
    gaps = selections.unattended_gaps(flags)
    assert gaps == []


@pytest.mark.unit
def test_a_profile_does_not_hide_missing_required_inputs(monkeypatch):
    """REQ-TA-FR-001: only analysts/rounds are supplied by the profile; a missing
    ticker/date/provider is still a gap."""
    _clear_profile_env(monkeypatch)
    flags = {"ticker": None, "date": "2026-01-10", "analysts": None,
             "save": True, "show": False, "html": None, "profile": "quick"}
    gaps = selections.unattended_gaps(flags)
    assert "--ticker" in gaps
    assert "--analysts" not in gaps  # supplied by the profile
    assert not any("TRADINGAGENTS_MAX_DEBATE_ROUNDS" in g for g in gaps)


@pytest.mark.unit
def test_omitted_profile_keeps_the_old_gap_requirements(monkeypatch):
    """REQ-TA-FR-001: with no profile, --analysts and the round env are required again."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)
    flags = {"ticker": "NVDA", "date": "2026-01-10", "analysts": None,
             "save": True, "show": False, "html": None, "profile": None}
    gaps = selections.unattended_gaps(flags)
    assert "--analysts" in gaps
    assert any("TRADINGAGENTS_MAX_DEBATE_ROUNDS" in g for g in gaps)


# --- the interactive questions --------------------------------------------------

def _no_prompt(*a, **k):
    raise AssertionError("prompted although the profile answered the step")


@pytest.mark.unit
def test_a_profile_skips_the_analyst_and_depth_questions(monkeypatch):
    """REQ-TA-FR-001: a selected profile supplies the analysts and the budgets, so
    neither the analyst checkbox nor the depth prompt appears."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(selections, "select_analysts", _no_prompt)
    monkeypatch.setattr(selections, "select_research_depth", _no_prompt)
    monkeypatch.setattr(selections, "get_ticker", lambda: "NVDA")
    monkeypatch.setattr(selections, "get_analysis_date", lambda: "2026-01-10")
    monkeypatch.setattr(selections.updates, "enabled", lambda: False)

    chosen = selections._prompt_selections({}, {"ticker": "NVDA", "date": "2026-01-10",
                                                "profile": "quick"})

    assert {a.value for a in chosen["analysts"]} == {"market", "news"}
    assert chosen["research_depth"] == 1  # quick debate budget, no prompt


@pytest.mark.unit
def test_a_flag_analyst_set_still_overrides_the_profile_in_the_prompt(monkeypatch):
    """REQ-TA-FR-001: --analysts overrides the profile's analyst set."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(selections, "select_analysts", _no_prompt)
    monkeypatch.setattr(selections, "select_research_depth", _no_prompt)
    monkeypatch.setattr(selections.updates, "enabled", lambda: False)

    chosen = selections._prompt_selections({}, {"ticker": "NVDA", "date": "2026-01-10",
                                                "analysts": "market,social",
                                                "profile": "quick"})

    assert {a.value for a in chosen["analysts"]} == {"market", "social"}


@pytest.mark.unit
def test_a_profile_does_not_print_a_stale_round_hint(monkeypatch):
    """REQ-TA-FR-001: the selection step does not print the profile's raw debate/risk
    numbers (e.g. 3/3) that could be mistaken for the effective configuration."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)
    printed = []
    monkeypatch.setattr(selections, "select_analysts", _no_prompt)
    monkeypatch.setattr(selections, "select_research_depth", _no_prompt)
    monkeypatch.setattr(selections.updates, "enabled", lambda: False)
    monkeypatch.setattr(selections.console, "print",
                        lambda *a, **k: printed.append(str(a[0]) if a else ""))

    selections._prompt_selections({}, {"ticker": "NVDA", "date": "2026-01-10", "profile": "deep"})

    text = " ".join(printed)
    assert "3 debate / 3 risk" not in text
    assert "Research depth from profile deep" in text


@pytest.mark.unit
def test_omitted_profile_keeps_the_original_questions(monkeypatch):
    """REQ-TA-FR-001: with no profile the analyst and depth questions still appear."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)
    asked = []
    monkeypatch.setattr(selections, "select_analysts",
                        lambda asset, default=None: asked.append("analysts") or [AnalystType.MARKET])
    monkeypatch.setattr(selections, "select_research_depth",
                        lambda default=None: asked.append("depth") or 3)
    monkeypatch.setattr(selections.updates, "enabled", lambda: False)

    chosen = selections._prompt_selections({}, {"ticker": "NVDA", "date": "2026-01-10",
                                                "profile": None})

    assert asked == ["analysts", "depth"]
    assert chosen["research_depth"] == 3


# --- _build_run_config ----------------------------------------------------------

SELECTIONS = {
    "research_depth": 5, "quick_think_llm": "q", "deep_think_llm": "d",
    "backend_url": None, "llm_provider": "openai",
    "google_thinking_level": None, "openai_reasoning_effort": None,
    "anthropic_effort": None, "output_language": "English",
}


@pytest.mark.unit
def test_a_profile_does_not_inject_the_stale_research_depth(monkeypatch):
    """REQ-TA-FR-001: with a profile, the interactive depth is not written into the
    round config, so it cannot fight the profile."""
    _clear_profile_env(monkeypatch)
    monkeypatch.setitem(cli_run.DEFAULT_CONFIG, "max_debate_rounds", 1)
    monkeypatch.setitem(cli_run.DEFAULT_CONFIG, "max_risk_discuss_rounds", 1)

    cfg = cli_run._build_run_config(SELECTIONS, checkpoint=None, profile="quick")

    # The config keeps DEFAULT_CONFIG's round values; the graph resolves the profile.
    assert cfg["max_debate_rounds"] == 1
    assert cfg["max_risk_discuss_rounds"] == 1


@pytest.mark.unit
def test_omitted_profile_still_maps_depth_to_rounds(monkeypatch):
    """REQ-TA-FR-001: with no profile, the depth answer maps to both rounds as before."""
    _clear_profile_env(monkeypatch)
    cfg = cli_run._build_run_config(SELECTIONS, checkpoint=None, profile=None)
    assert cfg["max_debate_rounds"] == 5
    assert cfg["max_risk_discuss_rounds"] == 5


# --- run_analysis: validation order and one resolved config ----------------------

class _FakeGraph:
    """A graph stand-in that records its constructor args and runs one empty step."""

    instances = []

    def __init__(self, selected_analysts=None, config=None, debug=False, callbacks=None, profile=None,
                 explicit_overrides=None, base_analysts=None):
        chosen = None
        if explicit_overrides and explicit_overrides.get("analysts"):
            chosen = explicit_overrides["analysts"]
        elif selected_analysts is not None:
            chosen = selected_analysts
        elif base_analysts is not None:
            chosen = base_analysts
        else:
            chosen = ("market", "news") if profile == "quick" else (
                "market", "social", "news", "fundamentals")
        self.selected_analysts = tuple(chosen)
        self.profile = profile
        self.config = config
        self.graph = self
        self.propagator = self
        self._resuming = False
        type(self).instances.append(self)

    def run_settings(self):
        analysts = list(self.selected_analysts)
        return {
            "analysts": analysts,
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "max_tool_rounds": 3 if self.profile == "quick" else 20,
            "profile_requested": self.profile,
        }

    def create_run_state(self, ticker, trade_date, asset_type="stock", portfolio=None):
        return {"messages": [], "company_of_interest": ticker}

    def record_decision(self, *a, **k):
        pass

    def get_graph_args(self, callbacks=None):
        return {}

    def begin_checkpoint(self, *a, **k):
        return None

    def checkpoint_input(self, state):
        return state

    def clear_checkpoint_on_success(self, *a, **k):
        pass

    def end_checkpoint(self):
        pass

    def stream_run(self, graph_input, **kwargs):
        yield [], {"messages": [], "financial_report": "x"}


class _NullLive:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Buffer:
    def __init__(self):
        self.selected_analysts = []
        self.messages = []
        self.tool_calls = []
        self.agent_status = {}
        self.report_sections = {}
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        self.selected_analysts = list(selected_analysts)

    def add_message(self, kind, content):
        self.messages.append((0.0, kind, content))

    def add_tool_call(self, name, args):
        self.tool_calls.append((0.0, name, args))

    def update_report_section(self, *a):
        pass

    def update_agent_status(self, *a):
        pass


def _wire_run(monkeypatch, tmp_path, selections_dict):
    graph = _FakeGraph
    graph.instances = []
    buffer = _Buffer()
    monkeypatch.setattr(cli_run, "TradingAgentsGraph", graph)
    monkeypatch.setattr(cli_run, "message_buffer", buffer)
    monkeypatch.setattr(cli_run, "create_layout", lambda: None)
    monkeypatch.setattr(cli_run, "update_display", lambda *a, **k: None)
    monkeypatch.setattr(cli_run, "Live", _NullLive)
    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags=None: selections_dict)
    monkeypatch.setattr(cli_run, "_build_run_config",
                        lambda selections, checkpoint, profile=None: {
                            "data_cache_dir": str(tmp_path / "cache"),
                            "results_dir": str(tmp_path / "results")})
    monkeypatch.setattr(cli_run.typer, "prompt", lambda *a, **k: "N")
    return graph, buffer


_SELECTIONS_DICT = {"ticker": "NVDA", "analysis_date": "2026-01-10", "asset_type": "stock",
                    "analysts": [AnalystType.MARKET, AnalystType.NEWS]}


@pytest.mark.unit
def test_run_analysis_passes_the_profile_and_shares_one_config(monkeypatch, tmp_path):
    """REQ-TA-FR-001: the graph receives the profile; the execution plan and the
    progress buffer read the graph's resolved analysts."""
    _clear_profile_env(monkeypatch)
    graph, buffer = _wire_run(monkeypatch, tmp_path, _SELECTIONS_DICT)

    cli_run.run_analysis(flags={"ticker": "NVDA", "date": "2026-01-10", "analysts": None,
                                "save": False, "show": False, "html": None}, profile="quick")

    assert graph.instances[-1].profile == "quick"
    # Progress buffer shows exactly the analysts the graph runs with.
    assert buffer.selected_analysts == ["market", "news"]


@pytest.mark.unit
def test_an_unknown_profile_fails_before_any_graph_or_prompt(monkeypatch, tmp_path, capsys):
    """REQ-TA-FR-001: an invalid profile errors before the gap check, prompts and
    model clients, naming the legal values; no graph is built."""
    _clear_profile_env(monkeypatch)
    graph, _ = _wire_run(monkeypatch, tmp_path, _SELECTIONS_DICT)
    monkeypatch.setattr(cli_run, "get_user_selections",
                        lambda flags=None: (_ for _ in ()).throw(AssertionError("prompted")))
    monkeypatch.setattr(cli_run.sys.stdin, "isatty", lambda: False)

    with pytest.raises(typer.Exit):
        cli_run.run_analysis(flags={"ticker": "NVDA", "date": "2026-01-10", "analysts": None,
                                    "save": True, "show": False, "html": None}, profile="turbo")

    out = capsys.readouterr().out
    for legal in ("quick", "standard", "deep"):
        assert legal in out
    assert graph.instances == []  # no model client / graph was created


@pytest.mark.unit
def test_a_valid_profile_runs_headless_with_config_omitted(monkeypatch, tmp_path):
    """REQ-TA-FR-001: with a profile, a headless run needs no --analysts or round
    env; other required inputs are answered, and the run reaches the graph."""
    _clear_profile_env(monkeypatch)
    for name, value in UNATTENDED_ENV.items():
        monkeypatch.setenv(name, value)
    graph, buffer = _wire_run(monkeypatch, tmp_path, _SELECTIONS_DICT)
    monkeypatch.setattr(cli_run.sys.stdin, "isatty", lambda: False)

    cli_run.run_analysis(flags={"ticker": "NVDA", "date": "2026-01-10", "analysts": None,
                                "save": False, "show": False, "html": None}, profile="quick")

    assert graph.instances[-1].profile == "quick"
    assert buffer.selected_analysts == ["market", "news"]


@pytest.mark.unit
def test_the_main_command_forwards_the_profile_flag(monkeypatch):
    """REQ-TA-FR-001: the typer command passes --profile through to run_analysis."""
    seen = {}
    monkeypatch.setattr(cli_main, "run_analysis", lambda **kw: seen.update(kw))
    from typer.testing import CliRunner

    result = CliRunner().invoke(cli_main.app, ["--profile", "deep", "--ticker", "NVDA",
                                               "--save", "--no-show"])
    assert result.exit_code == 0, result.output
    assert seen["profile"] == "deep"
