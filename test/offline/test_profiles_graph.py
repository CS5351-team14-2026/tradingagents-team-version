"""The graph adopts a resolved profile (REQ-TA-FR-001; ADR-002).

These tests pin that ``TradingAgentsGraph`` wires the profile's analyst set and
three round caps into the compiled graph, rejects an unknown profile before any
model client is built, honours an explicit Python profile over the environment,
overrides the profile per field, and keeps the checkpoint signature identical to
the pre-change baseline when no profile is given while distinguishing a profile
that changes the analysts or the rounds.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pandas as pd
import pytest

from tradingagents.agents import context
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"


class _StubModel:
    """A model stand-in; its identity is all the graph wiring needs here."""

    def invoke(self, *args, **kwargs):  # pragma: no cover - never called in these tests
        raise AssertionError("stub model must not be invoked by graph construction")


class _Client:
    def __init__(self, model):
        self.model = model

    def get_llm(self):
        return self.model


@pytest.fixture
def offline(monkeypatch):
    """Every vendor answers offline so graph construction never reaches the network."""
    for method, vendors in router.VENDOR_METHODS.items():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, _m=method, **k: f"{_m} data")
    prices = pd.DataFrame({
        "Date": pd.bdate_range(end=TRADE_DATE, periods=60),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000_000,
    })
    monkeypatch.setattr(snapshot, "load_ohlcv", lambda *a, **k: prices.copy())
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "no posts")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "no posts")
    monkeypatch.setattr(yahoo_market.yf, "Ticker", lambda s: type("T", (), {"info": {"longName": "NVIDIA"}})())
    context._identity.cache_clear()


def _config(tmp_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"))
    return cfg


def _build(tmp_path, monkeypatch, **kwargs):
    """Construct a graph with a client that never reaches a provider."""
    cfg = kwargs.pop("config", None) or _config(tmp_path)
    monkeypatch.setattr(trading_graph, "create_tier_client", lambda config, tier, **k: _Client(_StubModel()))
    return trading_graph.TradingAgentsGraph(config=cfg, **kwargs)


@pytest.mark.unit
@pytest.mark.parametrize("profile, analysts, debate, risk, tools", [
    ("quick", ("market", "news"), 1, 1, 3),
    ("standard", ("market", "social", "news", "fundamentals"), 1, 1, 20),
    ("deep", ("market", "social", "news", "fundamentals"), 3, 3, 20),
])
def test_the_graph_uses_the_profile_settings(tmp_path, monkeypatch, offline, profile, analysts, debate, risk, tools):
    """REQ-TA-FR-001: the analysis graph adopts the selected profile's four settings."""
    graph = _build(tmp_path, monkeypatch, profile=profile)

    assert graph.selected_analysts == analysts
    assert graph.conditional_logic.max_debate_rounds == debate
    assert graph.conditional_logic.max_risk_discuss_rounds == risk
    assert graph.graph_setup.max_tool_rounds == tools
    # The analysts actually wired into the compiled graph:
    nodes = set(graph.graph.get_graph().nodes)
    for key in analysts:
        node = {
            "market": "Market Analyst", "social": "Sentiment Analyst",
            "news": "News Analyst", "fundamentals": "Fundamentals Analyst",
        }[key]
        assert node in nodes
    assert "Fundamentals Analyst" not in nodes or "fundamentals" in analysts


@pytest.mark.unit
def test_an_unknown_profile_is_rejected_before_any_client_is_built(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: an invalid profile is rejected before any LLM call, naming the
    legal values; no model client is created."""
    created = []
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: created.append(tier) or _Client(_StubModel()))

    with pytest.raises(ValueError) as caught:
        trading_graph.TradingAgentsGraph(config=_config(tmp_path), profile="turbo")

    message = str(caught.value)
    for legal in ("quick", "standard", "deep"):
        assert legal in message
    assert created == []  # no deep/quick client was built


@pytest.mark.unit
@pytest.mark.parametrize("tool_cap", [0, -1, -20])
def test_a_tool_round_cap_below_one_is_rejected_before_any_client_is_built(
        tmp_path, monkeypatch, offline, tool_cap):
    """REQ-TA-FR-001 / REQ-TA-INV-003: a per-analyst tool-round cap below 1 is
    refused up front — zero and negative included — and no model client is
    created, so the run cannot start with a cap that never asks for a report."""
    created = []
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: created.append(tier) or _Client(_StubModel()))

    with pytest.raises(ValueError, match="max_tool_rounds") as caught:
        trading_graph.TradingAgentsGraph(
            config=_config(tmp_path), explicit_overrides={"max_tool_rounds": tool_cap})

    assert str(tool_cap) in str(caught.value)
    assert created == []  # no deep/quick client was built


@pytest.mark.unit
@pytest.mark.parametrize("tool_cap", ["0", "-3"])
def test_a_tool_round_env_cap_below_one_is_rejected_with_a_profile(
        tmp_path, monkeypatch, offline, tool_cap):
    """REQ-TA-FR-001 / REQ-TA-INV-003: the same guard catches a below-one cap that
    comes in through TRADINGAGENTS_MAX_TOOL_ROUNDS when a profile is selected."""
    created = []
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: created.append(tier) or _Client(_StubModel()))
    monkeypatch.setenv("TRADINGAGENTS_MAX_TOOL_ROUNDS", tool_cap)

    with pytest.raises(ValueError, match="max_tool_rounds"):
        trading_graph.TradingAgentsGraph(config=_config(tmp_path), profile="standard")

    assert created == []


@pytest.mark.unit
def test_an_explicit_python_profile_wins_over_the_environment(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: an explicitly passed profile beats TRADINGAGENTS_PROFILE."""
    monkeypatch.setenv("TRADINGAGENTS_PROFILE", "deep")
    graph = _build(tmp_path, monkeypatch, profile="quick")

    assert graph.profile_resolution.requested_profile == "quick"
    assert graph.selected_analysts == ("market", "news")
    assert (graph.conditional_logic.max_debate_rounds,
            graph.conditional_logic.max_risk_discuss_rounds) == (1, 1)


@pytest.mark.unit
def test_the_environment_profile_applies_when_none_is_passed(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: with no Python profile, TRADINGAGENTS_PROFILE selects the profile."""
    monkeypatch.setenv("TRADINGAGENTS_PROFILE", "deep")
    graph = _build(tmp_path, monkeypatch)

    assert graph.profile_resolution.requested_profile == "deep"
    assert graph.conditional_logic.max_debate_rounds == 3


@pytest.mark.unit
def test_explicit_round_override_keeps_the_other_profile_fields(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: deep with an explicit debate of 1 keeps the risk budget at 3."""
    graph = _build(tmp_path, monkeypatch, profile="deep",
                   explicit_overrides={"max_debate_rounds": 1})

    assert graph.conditional_logic.max_debate_rounds == 1
    assert graph.conditional_logic.max_risk_discuss_rounds == 3
    assert graph.graph_setup.max_tool_rounds == 20
    assert graph.selected_analysts == ("market", "social", "news", "fundamentals")


@pytest.mark.unit
def test_a_passed_analyst_list_overrides_the_profile(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: an explicitly passed analyst set is an override of just that
    field, and is recorded in profile_overrides."""
    graph = _build(tmp_path, monkeypatch, profile="quick",
                   selected_analysts=("market", "social", "news", "fundamentals"))

    assert graph.selected_analysts == ("market", "social", "news", "fundamentals")
    assert graph.run_settings()["profile_overrides"] == {
        "analysts": ["market", "social", "news", "fundamentals"]}
    # The round and tool budgets still come from the quick profile.
    assert (graph.conditional_logic.max_debate_rounds,
            graph.conditional_logic.max_risk_discuss_rounds,
            graph.graph_setup.max_tool_rounds) == (1, 1, 3)


@pytest.mark.unit
def test_explicit_overrides_analysts_wins_over_a_passed_selection(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: when both a caller selection and explicit_overrides['analysts']
    are given, the latter wins and is the override recorded."""
    graph = _build(tmp_path, monkeypatch, profile="quick",
                   selected_analysts=("market", "social", "news", "fundamentals"),
                   explicit_overrides={"analysts": ["market", "news"]})

    assert graph.selected_analysts == ("market", "news")
    assert graph.run_settings()["profile_overrides"] == {"analysts": ["market", "news"]}


@pytest.mark.unit
def test_a_base_analyst_set_is_not_recorded_as_an_override(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: the CLI's auto-selected base set shapes the resolved analysts but
    is not recorded in profile_overrides."""
    graph = _build(tmp_path, monkeypatch, profile="quick",
                   base_analysts=("market", "news"))

    assert graph.selected_analysts == ("market", "news")
    assert graph.run_settings()["profile_overrides"] == {}
    assert graph.run_settings()["profile_resolved"]["analysts"] == ["market", "news"]



@pytest.mark.unit
def test_an_env_round_override_is_read_at_its_value_with_a_profile(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: when a profile is selected, an env round override applies at
    its written value, not the base config's. deep + debate env=2 -> 2."""
    cfg = _config(tmp_path)
    cfg["max_debate_rounds"] = 3
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")

    graph = _build(tmp_path, monkeypatch, config=cfg, profile="deep")

    assert graph.conditional_logic.max_debate_rounds == 2
    # The other rounds keep the profile value.
    assert graph.conditional_logic.max_risk_discuss_rounds == 3


@pytest.mark.unit
def test_a_python_override_beats_the_same_env_variable_with_a_profile(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: with a profile selected, an explicit Python setting wins over
    the same env variable."""
    cfg = _config(tmp_path)
    cfg["max_debate_rounds"] = 3
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")

    graph = _build(tmp_path, monkeypatch, config=cfg, profile="deep",
                   explicit_overrides={"max_debate_rounds": 5})

    assert graph.conditional_logic.max_debate_rounds == 5


@pytest.mark.unit
def test_env_tool_cap_is_read_at_its_value_with_a_profile(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: with a profile, the tool-cap env override applies at its value."""
    monkeypatch.setenv("TRADINGAGENTS_MAX_TOOL_ROUNDS", "7")

    graph = _build(tmp_path, monkeypatch, profile="standard")

    assert graph.graph_setup.max_tool_rounds == 7


@pytest.mark.unit
def test_a_legacy_call_without_a_profile_ignores_the_environment(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001 backward compatibility: an omitted-profile caller that passes
    only the old config keeps the config values; a set env variable does not
    re-apply on top of them."""
    cfg = _config(tmp_path)
    cfg["max_debate_rounds"] = 1
    cfg["max_tool_rounds"] = 20
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")
    monkeypatch.setenv("TRADINGAGENTS_MAX_TOOL_ROUNDS", "5")

    graph = _build(tmp_path, monkeypatch, config=cfg)

    assert graph.profile_resolution.requested_profile is None
    assert graph.conditional_logic.max_debate_rounds == 1  # config value, not env 2
    assert graph.graph_setup.max_tool_rounds == 20          # config value, not env 5


@pytest.mark.unit
def test_a_legacy_call_keeps_the_config_rounds_without_a_profile(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001 backward compatibility: the old config round values are used
    verbatim when no profile is selected."""
    cfg = _config(tmp_path)
    cfg["max_debate_rounds"] = 4
    cfg["max_risk_discuss_rounds"] = 6
    cfg["max_tool_rounds"] = 9

    graph = _build(tmp_path, monkeypatch, config=cfg)

    assert graph.conditional_logic.max_debate_rounds == 4
    assert graph.conditional_logic.max_risk_discuss_rounds == 6
    assert graph.graph_setup.max_tool_rounds == 9


# The signature commit 03e7d48 (the pre-FR-001 baseline) produced for this exact
# config, computed with that commit's algorithm — an independent reference.
_SIGNATURE_COMMIT = "03e7d48"


def _pre_change_reference_signature(config, analysts, asset_type="stock"):
    """The signature as commit ``_SIGNATURE_COMMIT`` computed it, from first principles.

    The baseline algorithm took the config digest (minus the keys that never
    affect a checkpoint), the selected analysts, the debate/risk counts and the
    fixed layout markers; it had no tools segment, whatever the tool cap.
    """
    not_in_signature = frozenset({
        "results_dir", "data_cache_dir", "memory_log_path", "checkpoint_enabled", "llm_max_retries",
        "claim_enforcement",
    })
    settings = {k: v for k, v in config.items() if k not in not_in_signature}
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return "|".join([
        "analysts=" + ",".join(analysts),
        f"debate={config['max_debate_rounds']}",
        f"risk={config['max_risk_discuss_rounds']}",
        f"asset={asset_type}",
        "portfolio=none",
        "analysts=parallel",
        "memory=parallel",
        f"settings={digest}",
    ])


@pytest.mark.unit
@pytest.mark.parametrize("tool_cap", [20, 7])
def test_a_legacy_call_keeps_the_03e7d48_signature(tmp_path, monkeypatch, offline, tool_cap):
    """REQ-TA-FR-001: with no profile, the old call produces the 03e7d48 signature
    for both the default tool cap (20) and a custom one (7)."""
    cfg = _config(tmp_path)
    cfg["max_tool_rounds"] = tool_cap
    graph = _build(tmp_path, monkeypatch, config=cfg)

    assert graph.profile_resolution.requested_profile is None
    assert graph._run_signature("stock") == _pre_change_reference_signature(
        graph.config, graph.selected_analysts)


@pytest.mark.unit
def test_no_profile_keeps_the_pre_change_checkpoint_signature(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: an omitted profile reproduces the baseline checkpoint signature
    exactly, so an existing checkpoint still resumes."""
    graph = _build(tmp_path, monkeypatch)

    assert graph.profile_resolution.requested_profile is None
    assert graph._run_signature("stock") == _pre_change_reference_signature(
        graph.config, graph.selected_analysts)


@pytest.mark.unit
def test_a_profile_that_changes_rounds_yields_a_different_signature(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: a profile that changes the rounds does not reuse the baseline checkpoint."""
    baseline = _build(tmp_path / "a", monkeypatch)._run_signature("stock")
    deep = _build(tmp_path / "b", monkeypatch, profile="deep")._run_signature("stock")

    assert deep != baseline


@pytest.mark.unit
def test_a_profile_that_changes_analysts_yields_a_different_signature(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: a profile with a different analyst set is not resumed as the same run."""
    standard = _build(tmp_path / "a", monkeypatch, profile="standard")._run_signature("stock")
    quick = _build(tmp_path / "b", monkeypatch, profile="quick")._run_signature("stock")

    assert standard != quick


@pytest.mark.unit
def test_quick_and_deep_signatures_differ(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: any two distinct profiles never collide on the checkpoint signature."""
    sigs = {
        profile: _build(tmp_path / profile, monkeypatch, profile=profile)._run_signature("stock")
        for profile in ("quick", "standard", "deep")
    }
    assert len(set(sigs.values())) == 3


@pytest.mark.unit
def test_an_override_changing_the_tool_cap_changes_the_signature(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: on the same base config, moving the effective tool cap from 20
    to 3 via the new override parameter changes the signature."""
    cfg_a = _config(tmp_path / "a")
    cfg_a["max_tool_rounds"] = 20
    baseline = _build(tmp_path / "a", monkeypatch, config=cfg_a)._run_signature("stock")

    cfg_b = _config(tmp_path / "b")
    cfg_b["max_tool_rounds"] = 20
    changed = _build(tmp_path / "b", monkeypatch, config=cfg_b,
                     explicit_overrides={"max_tool_rounds": 3})._run_signature("stock")

    assert changed != baseline


@pytest.mark.unit
def test_the_pre_change_signature_for_a_fixed_config_is_unchanged(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: a fixed no-profile invocation keeps exactly the 03e7d48
    signature. The expected string is hard-coded from that commit's algorithm, not
    recomputed from the current code."""
    graph = trading_graph.TradingAgentsGraph.__new__(trading_graph.TradingAgentsGraph)
    graph.selected_analysts = ("market", "news")
    graph.config = {
        "results_dir": "X", "data_cache_dir": "Y", "memory_log_path": "Z",
        "checkpoint_enabled": False, "llm_max_retries": None,
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1, "max_tool_rounds": 20,
        "llm_provider": "openai", "deep_think_llm": "d", "quick_think_llm": "q",
    }

    expected = ("analysts=market,news|debate=1|risk=1|asset=stock|portfolio=none|"
                "analysts=parallel|memory=parallel|settings=28bd6315ccc7")
    assert graph._run_signature("stock") == expected


@pytest.mark.unit
def test_claim_enforcement_does_not_change_the_checkpoint_signature(tmp_path, monkeypatch, offline):
    """REQ-TA-FR-001: claim_enforcement is settled after the graph run, so a
    legacy config without the key and configs carrying False or True must share
    one signature — an existing checkpoint still resumes — and keep the 03e7d48 value."""
    base = {
        "results_dir": "X", "data_cache_dir": "Y", "memory_log_path": "Z",
        "checkpoint_enabled": False, "llm_max_retries": None,
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1, "max_tool_rounds": 20,
        "llm_provider": "openai", "deep_think_llm": "d", "quick_think_llm": "q",
    }

    def _signature(config):
        graph = trading_graph.TradingAgentsGraph.__new__(trading_graph.TradingAgentsGraph)
        graph.selected_analysts = ("market", "news")
        graph.config = config
        return graph._run_signature("stock")

    legacy = _signature(dict(base))
    with_false = _signature({**base, "claim_enforcement": False})
    with_true = _signature({**base, "claim_enforcement": True})

    assert with_false == legacy
    assert with_true == legacy
    assert legacy == ("analysts=market,news|debate=1|risk=1|asset=stock|portfolio=none|"
                      "analysts=parallel|memory=parallel|settings=28bd6315ccc7")
