"""Token-budget configuration surface (REQ-TA-FR-002; ADR-004 D6).

Offline tests of the ``token_budget`` config key: valid non-negative integers
disable off by default, a zero budget, env overlay, rejection of negatives and
booleans, and that an unset budget preserves the baseline.
"""

from __future__ import annotations

import pytest

import tradingagents.default_config as default_config_module
from tradingagents.default_config import build_default_config
from tradingagents.run_budget import RunBudgetTracker, budget_from_config


@pytest.mark.unit
def test_default_config_has_no_budget():
    """REQ-TA-FR-002 (D6): the default config disables enforcement."""
    assert build_default_config()["token_budget"] is None


@pytest.mark.unit
def test_env_override_sets_budget(monkeypatch):
    """REQ-TA-FR-002: TRADINGAGENTS_TOKEN_BUDGET sets the run budget."""
    for key in list(default_config_module._ENV_OVERRIDES):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRADINGAGENTS_TOKEN_BUDGET", "5000")
    assert build_default_config()["token_budget"] == 5000


@pytest.mark.unit
def test_env_non_integer_budget_fails_loudly(monkeypatch):
    """REQ-TA-FR-002: a non-integer budget is rejected at startup, not silently ignored."""
    for key in list(default_config_module._ENV_OVERRIDES):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRADINGAGENTS_TOKEN_BUDGET", "lots")
    with pytest.raises(ValueError):
        build_default_config()


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-1, True, False, 1.5, "10"])
def test_tracker_rejects_invalid_limit(bad):
    """REQ-TA-FR-002 (D6): negative, boolean and non-int budgets are invalid."""
    with pytest.raises(ValueError):
        RunBudgetTracker(bad)


@pytest.mark.unit
def test_zero_budget_is_valid_and_blocks_optional_immediately():
    """REQ-TA-FR-002 (D6): zero is valid; it blocks optional calls at once (known 0 >= 0)."""
    from tradingagents.run_budget import USAGE_COMPLETE, CallRole, UsageObservation

    t = RunBudgetTracker(0)
    t.start_call("a", role=CallRole.REQUIRED, phase="x")
    t.finish_call("a", UsageObservation(0, 0, USAGE_COMPLETE))
    assert t.try_start(call_id="b", role=CallRole.OPTIONAL, phase="d").allowed is False


@pytest.mark.unit
def test_budget_from_config_reads_key():
    """REQ-TA-FR-002: budget_from_config maps config to a tracker (None -> disabled)."""
    assert budget_from_config({"token_budget": None}).limit is None
    assert budget_from_config({"token_budget": 250}).limit == 250
    assert budget_from_config({}).limit is None
