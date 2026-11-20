"""Provider usage normalization: unknown never becomes zero (REQ-TA-FR-002; ADR-004).

These are offline, deterministic tests of ``llm_clients.usage.normalize_usage``
and ``UsageCallbackHandler``. They pin the D1/D2 contract: a reported zero is
distinct from a missing field; standardized ``usage_metadata`` and known
provider raw shapes are read without estimation; duplicate callback delivery
replaces rather than adds.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tradingagents.llm_clients.usage import UsageCallbackHandler, normalize_usage
from tradingagents.run_budget import (
    USAGE_COMPLETE,
    USAGE_CONFLICT,
    USAGE_PARTIAL,
    USAGE_UNAVAILABLE,
    CallRole,
    RunBudgetTracker,
)


def _result(usage_metadata=None, response_metadata=None):
    message = AIMessage(
        content="x",
        usage_metadata=usage_metadata,
        response_metadata=response_metadata or {},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


@pytest.mark.unit
def test_complete_standardized_usage_is_complete():
    """REQ-TA-FR-002: input+output both reported -> complete."""
    obs = normalize_usage(_result({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}))
    assert obs.state == USAGE_COMPLETE
    assert obs.tokens_in == 10 and obs.tokens_out == 5
    assert obs.known_tokens == 15


@pytest.mark.unit
def test_total_mismatch_is_conflict_not_guessed():
    """REQ-TA-FR-002 (D2): contradictory metadata is conflict, never a chosen value."""
    obs = normalize_usage(_result({"input_tokens": 10, "output_tokens": 5, "total_tokens": 99}))
    assert obs.state == USAGE_CONFLICT
    assert obs.known_tokens is None


@pytest.mark.unit
def test_single_side_is_partial_lower_bound():
    """REQ-TA-FR-002 (D1): one reported side is a lower bound, not a complete total."""
    from tradingagents.llm_clients.usage import _from_usage_metadata

    # AIMessage validates usage_metadata.total_tokens, so exercise the raw
    # normalizer with the single-side shape a provider may emit.
    obs = _from_usage_metadata({"input_tokens": 10})
    assert obs.state == USAGE_PARTIAL
    assert obs.known_tokens == 10


@pytest.mark.unit
def test_no_usage_is_unavailable_never_zero():
    """REQ-TA-FR-002 (D2): a provider that reports nothing yields unavailable, not 0."""
    obs = normalize_usage(_result())
    assert obs.state == USAGE_UNAVAILABLE
    assert obs.tokens_in is None and obs.tokens_out is None
    assert obs.known_tokens is None


@pytest.mark.unit
def test_genuine_zero_is_complete_not_unavailable():
    """REQ-TA-FR-002: a reported zero is a real measurement, distinct from unknown."""
    obs = normalize_usage(_result({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}))
    assert obs.state == USAGE_COMPLETE
    assert obs.known_tokens == 0


@pytest.mark.unit
def test_anthropic_raw_usage_sums_cache_fields_once():
    """REQ-TA-FR-002 (D1): Anthropic cache read/creation add to input, not double counted."""
    raw = {
        "input_tokens": 100,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 5,
        "output_tokens": 40,
    }
    obs = normalize_usage(_result(response_metadata={"usage": raw}), provider="anthropic")
    assert obs.state == USAGE_COMPLETE
    assert obs.tokens_in == 125
    assert obs.tokens_out == 40


@pytest.mark.unit
def test_google_raw_usage_sums_prompt_and_tool_and_thoughts():
    """REQ-TA-FR-002 (D1): Google prompt+tool-use in, candidate+thoughts out."""
    raw = {
        "promptTokenCount": 100,
        "toolUsePromptTokenCount": 10,
        "candidatesTokenCount": 30,
        "thoughtsTokenCount": 5,
    }
    obs = normalize_usage(_result(response_metadata={"usage_metadata": raw}), provider="google")
    assert obs.state == USAGE_COMPLETE
    assert obs.tokens_in == 110
    assert obs.tokens_out == 35


@pytest.mark.unit
def test_missing_anthropic_field_stays_null_not_zero():
    """REQ-TA-FR-002 (D2): a missing additive field is not filled with zero."""
    raw = {"input_tokens": 100, "output_tokens": None}
    obs = normalize_usage(_result(response_metadata={"usage": raw}), provider="anthropic")
    assert obs.state == USAGE_PARTIAL
    assert obs.tokens_out is None


@pytest.mark.unit
def test_callback_handler_records_and_dedupes_by_run_id():
    """REQ-TA-FR-002 (D5): duplicate delivery of one call replaces, never double counts."""
    tracker = RunBudgetTracker(limit=1000)
    handler = UsageCallbackHandler(tracker)
    handler.on_chat_model_start({}, [], run_id="c1")
    handler.on_llm_end(_result({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}), run_id="c1")
    handler.on_llm_end(_result({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}), run_id="c1")
    tracker.start_call("c1", role=CallRole.REQUIRED, phase="x")
    snap = tracker.snapshot()
    assert snap.llm_calls == 1
    assert snap.tokens_in == 10 and snap.tokens_out == 5


@pytest.mark.unit
def test_callback_error_marks_usage_unknown():
    """REQ-TA-FR-002 (D2): a failed call is unknown, not zero."""
    tracker = RunBudgetTracker(limit=1000)
    handler = UsageCallbackHandler(tracker)
    handler.on_llm_start({}, ["p"], run_id="c1")
    handler.on_llm_error(RuntimeError("boom"), run_id="c1")
    snap = tracker.snapshot()
    assert snap.usage_complete is False
    assert snap.tokens_in is None
