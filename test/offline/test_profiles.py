"""Analysis-profile resolution (REQ-TA-FR-001; ADR-002).

The four settings a profile bundles are the analyst set, the Bull/Bear debate
budget, the risk-discussion budget and the per-analyst tool-round cap. These
tests pin the approved mapping, the rejection of an unknown profile before any
model is built, the baseline behaviour when no profile is given, and per-field
explicit overrides.
"""

from __future__ import annotations

import pytest

from tradingagents.default_config import (
    PROFILE_MAPPING,
    PROFILE_NAMES,
    resolve_profile,
)

# The approved mapping, written out independently of the implementation so a
# silent edit of PROFILE_MAPPING fails here (REQ-TA-FR-001).
APPROVED = {
    "quick": (("market", "news"), 1, 1, 3),
    "standard": (("market", "social", "news", "fundamentals"), 1, 1, 20),
    "deep": (("market", "social", "news", "fundamentals"), 3, 3, 20),
}


def _tuple(settings):
    return (
        tuple(settings["analysts"]),
        settings["max_debate_rounds"],
        settings["max_risk_discuss_rounds"],
        settings["max_tool_rounds"],
    )


@pytest.mark.unit
@pytest.mark.parametrize("profile", list(APPROVED))
def test_each_profile_applies_its_approved_mapping(profile):
    """REQ-TA-FR-001: a valid profile applies the approved four settings exactly."""
    resolved = resolve_profile(profile)
    assert _tuple(resolved.resolved_settings()) == APPROVED[profile]
    assert resolved.requested_profile == profile
    assert resolved.overrides == {}


@pytest.mark.unit
def test_profile_names_are_the_approved_three_in_order():
    """REQ-TA-FR-001: the legal values are exactly quick, standard, deep."""
    assert PROFILE_NAMES == ("quick", "standard", "deep")
    assert set(PROFILE_MAPPING) == {"quick", "standard", "deep"}


@pytest.mark.unit
@pytest.mark.parametrize("profile", ["turbo", "QUICK", "", "deep ", "standard "])
def test_an_unknown_profile_is_rejected_naming_the_legal_values(profile):
    """REQ-TA-FR-001: an invalid profile is rejected before any LLM call, listing
    the legal values."""
    with pytest.raises(ValueError) as caught:
        resolve_profile(profile)
    message = str(caught.value)
    for legal in ("quick", "standard", "deep"):
        assert legal in message


@pytest.mark.unit
def test_none_reproduces_the_baseline_without_a_profile_key():
    """REQ-TA-FR-001: unset profile reproduces v0.7.1 defaults exactly."""
    defaults = {
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_rounds": 20,
    }
    resolved = resolve_profile(None, defaults=defaults)
    assert resolved.requested_profile is None
    assert resolved.analysts == ("market", "social", "news", "fundamentals")
    assert resolved.max_debate_rounds == 1
    assert resolved.max_risk_discuss_rounds == 1
    assert resolved.max_tool_rounds == 20
    assert resolved.overrides == {}


@pytest.mark.unit
def test_none_honours_environment_folded_defaults():
    """REQ-TA-FR-001: with no profile, the env-applied DEFAULT_CONFIG values apply."""
    defaults = {
        "max_debate_rounds": 3,
        "max_risk_discuss_rounds": 2,
        "max_tool_rounds": 10,
    }
    resolved = resolve_profile(None, defaults=defaults)
    assert (resolved.max_debate_rounds, resolved.max_risk_discuss_rounds, resolved.max_tool_rounds) == (3, 2, 10)


@pytest.mark.unit
def test_deep_with_explicit_debate_one_keeps_risk_at_three():
    """REQ-TA-FR-001: explicit settings override the profile per field only.

    The headline case: deep with an explicit debate of 1 must leave the risk
    budget at the profile's 3 and the tool cap at 20.
    """
    resolved = resolve_profile("deep", explicit={"max_debate_rounds": 1})
    assert resolved.max_debate_rounds == 1
    assert resolved.max_risk_discuss_rounds == 3
    assert resolved.max_tool_rounds == 20
    assert resolved.analysts == ("market", "social", "news", "fundamentals")
    assert resolved.overrides == {"max_debate_rounds": 1}


@pytest.mark.unit
def test_explicit_analysts_override_only_the_analyst_field():
    """REQ-TA-FR-001: an explicit analyst set overrides just the analysts field."""
    resolved = resolve_profile("quick", explicit={"analysts": ["market", "social"]})
    assert resolved.analysts == ("market", "social")
    assert (resolved.max_debate_rounds, resolved.max_risk_discuss_rounds, resolved.max_tool_rounds) == (1, 1, 3)
    assert resolved.overrides == {"analysts": ["market", "social"]}


@pytest.mark.unit
def test_several_explicit_fields_override_independently():
    """REQ-TA-FR-001: each explicit field overrides its own setting, others keep the profile."""
    resolved = resolve_profile(
        "deep",
        explicit={"max_debate_rounds": 1, "max_tool_rounds": 5},
    )
    assert resolved.max_debate_rounds == 1
    assert resolved.max_risk_discuss_rounds == 3  # still the profile's value
    assert resolved.max_tool_rounds == 5
    assert resolved.overrides == {"max_debate_rounds": 1, "max_tool_rounds": 5}


@pytest.mark.unit
def test_all_four_fields_can_be_overridden():
    """REQ-TA-FR-001: every profile field is independently overridable."""
    explicit = {
        "analysts": ["news"],
        "max_debate_rounds": 2,
        "max_risk_discuss_rounds": 4,
        "max_tool_rounds": 7,
    }
    resolved = resolve_profile("standard", explicit=explicit)
    assert resolved.analysts == ("news",)
    assert (resolved.max_debate_rounds, resolved.max_risk_discuss_rounds, resolved.max_tool_rounds) == (2, 4, 7)
    assert resolved.overrides == explicit


@pytest.mark.unit
def test_no_profile_but_explicit_values_still_apply():
    """REQ-TA-FR-001: a half-configured run may set settings without a profile."""
    resolved = resolve_profile(None, explicit={"max_tool_rounds": 8},
                               defaults={"max_debate_rounds": 1, "max_risk_discuss_rounds": 1,
                                         "max_tool_rounds": 20})
    assert resolved.requested_profile is None
    assert resolved.max_tool_rounds == 8
    assert resolved.max_debate_rounds == 1
    assert resolved.overrides == {"max_tool_rounds": 8}


@pytest.mark.unit
def test_an_unknown_override_field_is_rejected():
    """REQ-TA-FR-001: only the four profile settings may be overridden."""
    with pytest.raises(ValueError, match="temperature"):
        resolve_profile("quick", explicit={"temperature": 0.2})
