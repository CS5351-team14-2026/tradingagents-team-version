"""Usage adapter evidence for REQ-TA-FR-002, REQ-TA-QR-004 and QR-005 (ADR-003)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from cli.stats_handler import StatsCallbackHandler
from tradingagents.llm_clients.usage import UsageCallbackHandler, normalize_usage
from tradingagents.run_budget import RunBudgetContext, RunBudgetTracker


def _message(usage=None, metadata=None):
    return SimpleNamespace(usage_metadata=usage, response_metadata=metadata)


def _result(*groups, aggregate=None):
    return SimpleNamespace(
        generations=[[SimpleNamespace(message=message) for message in group] for group in groups],
        llm_output=aggregate,
    )


@pytest.mark.unit
@pytest.mark.parametrize("tokens_in,tokens_out", [(12, 7), (0, 0)])
def test_fr002_normalizes_real_message_usage_including_reported_zero(tokens_in, tokens_out):
    """REQ-TA-FR-002: only an explicit provider zero is a measured zero."""
    message = AIMessage(content="report", usage_metadata={
        "input_tokens": tokens_in, "output_tokens": tokens_out,
        "total_tokens": tokens_in + tokens_out,
    })
    response = LLMResult(generations=[[ChatGeneration(message=message)]])
    usage = normalize_usage(response)
    assert usage.state == "complete"
    assert usage.tokens_in == tokens_in
    assert usage.tokens_out == tokens_out
    assert usage.total_tokens == tokens_in + tokens_out


@pytest.mark.unit
@pytest.mark.parametrize("usage,expected_in,expected_out,expected_total", [
    ({"input_tokens": 12}, 12, None, None),
    ({"output_tokens": 7}, None, 7, None),
    ({"total_tokens": 19}, None, None, 19),
    ({"input_tokens": 0}, 0, None, None),
])
def test_fr002_partial_usage_keeps_unknown_fields(usage, expected_in, expected_out, expected_total):
    """REQ-TA-FR-002 / QR-004: preserve partial counts without inventing missing values."""
    observed = normalize_usage(_message(usage))
    assert observed.state == "partial"
    assert (observed.tokens_in, observed.tokens_out, observed.total_tokens) == (
        expected_in, expected_out, expected_total)


@pytest.mark.unit
@pytest.mark.parametrize("response", [
    None, {}, _message(), _message({}), _message({"input_tokens": None}),
    _result(), _result([]), SimpleNamespace(generations=None, llm_output={}),
])
def test_fr002_missing_usage_is_unavailable(response):
    """REQ-TA-FR-002: absent usage is unavailable, never a fabricated zero."""
    observed = normalize_usage(response)
    assert observed.state == "unavailable"
    assert observed.tokens_in is None
    assert observed.tokens_out is None
    assert observed.total_tokens is None


@pytest.mark.unit
@pytest.mark.parametrize("counts", [
    {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
    {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
    {"inputTokens": 12, "outputTokens": 7, "totalTokens": 19},
    {"promptTokenCount": 12, "toolUsePromptTokenCount": 0,
     "candidatesTokenCount": 7, "thoughtsTokenCount": 0, "totalTokenCount": 19},
    {"prompt_token_count": 12, "tool_use_prompt_token_count": 0,
     "candidates_token_count": 7, "thoughts_token_count": 0, "total_token_count": 19},
])
@pytest.mark.parametrize("wrapper", ["token_usage", "usage", "usage_metadata"])
def test_fr002_known_provider_shapes_are_read_once(counts, wrapper):
    """REQ-TA-FR-002: normalize published provider fields without price or token estimates."""
    observed = normalize_usage(_result([], aggregate={wrapper: counts}))
    assert observed.state == "complete"
    assert (observed.tokens_in, observed.tokens_out, observed.total_tokens) == (12, 7, 19)


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["anthropic", "google"])
@pytest.mark.parametrize("counts,state,known", [
    ({"input_tokens": 12, "output_tokens": 7, "total_tokens": 19}, "complete", 19),
    ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "complete", 0),
    ({"input_tokens": 12}, "partial", 12),
])
def test_fr002_standard_usage_wrapper_keeps_canonical_semantics(provider, counts, state, known):
    """REQ-TA-FR-002: provider hints cannot reinterpret standardized usage fields."""
    observed = normalize_usage(_result([], aggregate={"usage_metadata": counts}), provider=provider)
    assert observed.state == state
    assert observed.known_tokens == known


@pytest.mark.unit
def test_fr002_response_metadata_fallback_is_supported():
    """REQ-TA-FR-002: provider usage can be reported outside usage_metadata."""
    observed = normalize_usage(_message(metadata={
        "token_usage": {"prompt_tokens": 12, "completion_tokens": 7}}))
    assert observed.state == "complete"
    assert observed.total_tokens == 19


@pytest.mark.unit
def test_fr002_anthropic_cache_components_are_additive_once():
    """REQ-TA-FR-002: Anthropic base input excludes read/create cache tokens."""
    observed = normalize_usage(_message(metadata={"usage": {
        "input_tokens": 10, "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 5, "output_tokens": 7,
        "cache_creation": {"ephemeral_5m_input_tokens": 2, "ephemeral_1h_input_tokens": 3},
        "output_tokens_details": {"thinking_tokens": 4},
    }}), provider="anthropic")
    assert observed.state == "complete"
    assert (observed.tokens_in, observed.tokens_out, observed.total_tokens) == (35, 7, 42)


@pytest.mark.unit
def test_fr002_anthropic_standardized_cached_usage_has_no_false_raw_conflict():
    """REQ-TA-FR-002: cached canonical input and native base input have different meanings."""
    observed = normalize_usage(_message(
        {"input_tokens": 35, "output_tokens": 7, "total_tokens": 42},
        {"usage": {"input_tokens": 10, "cache_read_input_tokens": 20,
                   "cache_creation_input_tokens": 5, "output_tokens": 7}}), provider="anthropic")
    assert observed.state == "complete"
    assert observed.total_tokens == 42


@pytest.mark.unit
def test_fr002_anthropic_raw_missing_cache_fields_are_not_assumed_zero():
    """REQ-TA-FR-002: raw base input cannot stand for unknown canonical cached input."""
    observed = normalize_usage(_message(metadata={
        "usage": {"input_tokens": 10, "output_tokens": 7}}), provider="anthropic")
    assert observed.state == "partial"
    assert observed.tokens_in is None
    assert observed.tokens_out == 7
    assert observed.total_tokens is None


@pytest.mark.unit
def test_fr002_verified_canonical_native_usage_remains_complete():
    """REQ-TA-FR-002: partial native decomposition does not discard complete canonical usage."""
    observed = normalize_usage(_message(
        {"input_tokens": 35, "output_tokens": 7, "total_tokens": 42},
        {"usage": {"input_tokens": 10, "output_tokens": 7}}), provider="anthropic")
    assert observed.state == "complete"
    assert observed.total_tokens == 42


@pytest.mark.unit
def test_fr002_google_native_tool_and_thought_tokens_are_additive_once():
    """REQ-TA-FR-002: Google cached content is a subset, while tools/thoughts are additive."""
    observed = normalize_usage(_message(metadata={"usageMetadata": {
        "promptTokenCount": 10, "toolUsePromptTokenCount": 2,
        "candidatesTokenCount": 7, "thoughtsTokenCount": 5,
        "cachedContentTokenCount": 8, "totalTokenCount": 24,
    }}), provider="google")
    assert observed.state == "complete"
    assert (observed.tokens_in, observed.tokens_out, observed.total_tokens) == (12, 12, 24)


@pytest.mark.unit
def test_fr002_google_standardized_thought_usage_has_no_false_raw_conflict():
    """REQ-TA-FR-002: native candidate output alone does not include Google's thought tokens."""
    observed = normalize_usage(_message(
        {"input_tokens": 12, "output_tokens": 12, "total_tokens": 24},
        {"usageMetadata": {"promptTokenCount": 10, "toolUsePromptTokenCount": 2,
                           "candidatesTokenCount": 7, "thoughtsTokenCount": 5,
                           "totalTokenCount": 24}}), provider="google")
    assert observed.state == "complete"
    assert observed.total_tokens == 24


@pytest.mark.unit
def test_fr002_google_missing_native_additive_parts_keep_published_total_partial():
    """REQ-TA-FR-002: raw missing tool/thought counts are unknown; exact total stays reported."""
    observed = normalize_usage(_message(metadata={"usageMetadata": {
        "promptTokenCount": 10, "candidatesTokenCount": 7, "totalTokenCount": 24,
    }}), provider="google")
    assert observed.state == "partial"
    assert observed.tokens_in is None
    assert observed.tokens_out is None
    assert observed.total_tokens == 24


@pytest.mark.unit
@pytest.mark.parametrize("raw", [{}, {"prompt_tokens": 12}])
def test_fr002_openai_sdk_default_zero_cannot_complete_missing_raw_usage(raw):
    """REQ-TA-FR-002: SDK-filled zero does not replace a missing provider field."""
    observed = normalize_usage(_message(
        {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12},
        {"token_usage": raw}), provider="openai")
    assert observed.state == ("partial" if raw else "unavailable")
    assert observed.tokens_out is None
    assert observed.total_tokens is None


@pytest.mark.unit
def test_fr002_openai_explicit_raw_zero_is_a_complete_measurement():
    """REQ-TA-FR-002: preserve provider-reported zero despite SDK absence safeguards."""
    observed = normalize_usage(_message(
        {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        {"token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}),
        provider="openai")
    assert observed.state == "complete"
    assert observed.total_tokens == 0


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-1, True, False, "12", 12.5])
def test_fr002_invalid_usage_is_not_coerced(bad):
    """REQ-TA-FR-002: malformed provider counts do not become estimates or zero."""
    observed = normalize_usage(_message({"input_tokens": bad, "output_tokens": 3}))
    assert observed.state == "conflict"
    assert observed.tokens_in is None
    assert observed.tokens_out == 3


@pytest.mark.unit
@pytest.mark.parametrize("usage", [
    {"input_tokens": 12, "prompt_tokens": 13, "output_tokens": 7},
    {"input_tokens": 12, "output_tokens": 7, "total_tokens": 20},
    {"input_tokens": 12, "total_tokens": 11},
])
def test_fr002_conflicting_provider_fields_remain_incomplete(usage):
    """REQ-TA-FR-002 / QR-004: inconsistent usage cannot be advertised as complete."""
    assert normalize_usage(_message(usage)).state == "conflict"


@pytest.mark.unit
def test_fr002_duplicate_provider_metadata_is_not_added_again():
    """REQ-TA-FR-002: standard, raw, and aggregate reports of one usage are counted once."""
    counts = {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19}
    message = _message(counts, {"usage": counts})
    observed = normalize_usage(_result([message], aggregate={"usage": counts}))
    assert observed.state == "complete"
    assert observed.total_tokens == 19


@pytest.mark.unit
def test_fr002_alternate_generations_are_all_inspected_without_multiplying_usage():
    """REQ-TA-FR-002: inspect later generations without adding repeated request totals."""
    usage = {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19}
    observed = normalize_usage(_result([_message(), _message(usage), _message(usage)]))
    assert observed.state == "complete"
    assert observed.total_tokens == 19


@pytest.mark.unit
def test_fr002_distinct_batch_prompts_are_additive():
    """REQ-TA-FR-002: each prompt's published usage contributes once."""
    usage = {"input_tokens": 12, "output_tokens": 7}
    observed = normalize_usage(_result([_message(usage)], [_message(usage)]))
    assert observed.state == "complete"
    assert (observed.tokens_in, observed.tokens_out, observed.total_tokens) == (24, 14, 38)


@pytest.mark.unit
def test_fr002_missing_batch_usage_is_partial():
    """REQ-TA-FR-002: a reported batch subset is a lower bound, not a full measurement."""
    observed = normalize_usage(_result([
        _message({"input_tokens": 12, "output_tokens": 7})], [_message()]))
    assert observed.state == "partial"
    assert observed.tokens_in == 12
    assert observed.tokens_out == 7


@pytest.mark.unit
@pytest.mark.parametrize("groups,known", [
    (([{"input_tokens": 3, "output_tokens": 2}], [{"input_tokens": 3}]), 8),
    (([{"input_tokens": 3, "output_tokens": 2}], [{"total_tokens": 20}]), 25),
])
def test_fr002_partial_batch_keeps_each_prompt_lower_bound(groups, known):
    """REQ-TA-FR-002: a partial prompt does not disappear from the known-token sum."""
    observed = normalize_usage(_result(*[
        [_message(counts) for counts in group] for group in groups
    ]))
    assert observed.state == "partial"
    assert observed.known_tokens == known
    assert observed.source == "generations_lower_bound"


@pytest.mark.unit
def test_fr002_richer_batch_callback_upgrades_a_reported_lower_bound():
    """REQ-TA-FR-002: a later full measurement replaces the partial floor once."""
    handler = UsageCallbackHandler()
    handler.on_chat_model_start({}, [], run_id="batch")
    handler.on_llm_end(_result([
        _message({"input_tokens": 3, "output_tokens": 2})], [
        _message({"input_tokens": 3})]), run_id="batch")
    assert handler.tracker.snapshot().known_tokens == 8
    assert handler.get_stats()["usage_complete"] is False
    handler.on_llm_end(_result([
        _message({"input_tokens": 3, "output_tokens": 2})], [
        _message({"input_tokens": 3, "output_tokens": 4})]), run_id="batch")
    assert handler.get_stats()["usage_complete"] is True
    assert handler.get_stats()["total_tokens"] == 12
    assert handler.get_stats()["llm_calls"] == 1


@pytest.mark.unit
def test_fr002_complete_aggregate_covers_missing_per_message_usage():
    """REQ-TA-FR-002: a published aggregate needs no per-generation estimates."""
    observed = normalize_usage(_result([
        _message({"input_tokens": 12})], [_message()],
        aggregate={"token_usage": {"prompt_tokens": 20, "completion_tokens": 10}}))
    assert observed.state == "complete"
    assert observed.total_tokens == 30


@pytest.mark.unit
def test_fr002_batch_lower_bound_cannot_exceed_published_aggregate():
    """REQ-TA-FR-002: an aggregate smaller than a partial lower bound is conflict."""
    observed = normalize_usage(_result([
        _message({"total_tokens": 30})], [_message()],
        aggregate={"usage": {"input_tokens": 12, "output_tokens": 7}}))
    assert observed.state == "conflict"


@pytest.mark.unit
def test_fr002_partial_aggregate_components_remain_lower_bounds():
    """REQ-TA-FR-002: missing aggregate components cannot contradict a known batch sum."""
    observed = normalize_usage(_result([
        _message({"input_tokens": 12})], [_message()],
        aggregate={"usage": {"output_tokens": 7}}))
    assert observed.state == "partial"
    assert observed.tokens_out == 7


@pytest.mark.unit
def test_fr002_exact_single_prompt_partial_must_corroborate_aggregate():
    """REQ-TA-FR-002: partial input usage is exact for its single prompt."""
    observed = normalize_usage(_result([_message({"input_tokens": 3})],
        aggregate={"usage": {"input_tokens": 4, "output_tokens": 2}}))
    assert observed.state == "conflict"


@pytest.mark.unit
@pytest.mark.parametrize("aggregate,groups,known", [
    ({"input_tokens": 3}, ([{"total_tokens": 10}], [{}]), 10),
    ({"input_tokens": 3}, ([{"output_tokens": 10}], [{}]), 13),
    ({"input_tokens": 3}, ([{"input_tokens": 2, "output_tokens": 4}], [{}]), 7),
])
def test_fr002_partial_aggregate_preserves_stronger_batch_lower_bound(aggregate, groups, known):
    """REQ-TA-FR-002: overlapping partial observations combine by floor, never addition."""
    observed = normalize_usage(_result(*[
        [_message(counts) for counts in group] for group in groups
    ], aggregate={"usage": aggregate}))
    assert observed.state == "partial"
    assert observed.source == "generations_lower_bound"
    assert observed.known_tokens == known


@pytest.mark.unit
def test_fr002_conflicting_aggregate_is_not_added_to_message_usage():
    """REQ-TA-FR-002: contradictory aggregate and message measurements remain conflict."""
    observed = normalize_usage(_result([
        _message({"input_tokens": 12, "output_tokens": 7})],
        aggregate={"usage": {"input_tokens": 13, "output_tokens": 7}}))
    assert observed.state == "conflict"


@pytest.mark.unit
def test_fr002_callbacks_and_handlers_share_one_call_ledger():
    """REQ-TA-FR-002: constructor plus graph callback registration cannot double count."""
    tracker = RunBudgetTracker()
    graph_handler, cli_handler = UsageCallbackHandler(), StatsCallbackHandler()
    call_id = uuid4()
    result = _result([_message({"input_tokens": 12, "output_tokens": 7})])
    with RunBudgetContext(tracker).activate():
        for handler in (graph_handler, cli_handler):
            handler.on_llm_start({}, [], run_id=call_id)
            handler.on_chat_model_start({}, [], run_id=call_id)
            handler.on_llm_end(result, run_id=call_id)
            handler.on_llm_end(result, run_id=call_id)
            handler.on_tool_start({}, "", run_id="tool-one")
        stats = cli_handler.get_stats()
    assert stats["llm_calls"] == 1
    assert stats["tool_calls"] == 1
    assert stats["tokens_in"] == 12
    assert stats["tokens_out"] == 7
    assert stats["usage_complete"] is True


@pytest.mark.unit
def test_fr002_shared_handler_retains_per_call_provider_semantics():
    """REQ-TA-FR-002: quick/deep models can use distinct provider usage conventions."""
    handler = UsageCallbackHandler()
    handler.on_chat_model_start({}, [], run_id="anthropic", metadata={"ls_provider": "anthropic"})
    handler.on_chat_model_start({}, [], run_id="openai", metadata={"ls_provider": "openai"})
    handler.on_llm_end(_result([_message(
        {"input_tokens": 35, "output_tokens": 7, "total_tokens": 42},
        {"usage": {"input_tokens": 10, "output_tokens": 7}})]), run_id="anthropic")
    handler.on_llm_end(_result([_message(
        {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12},
        {"token_usage": {"prompt_tokens": 12}})]), run_id="openai")
    stats = handler.get_stats()
    assert stats["tokens_in"] == 47
    assert stats["tokens_out"] == 7
    assert stats["usage_complete"] is False


@pytest.mark.unit
def test_fr002_callback_missing_usage_does_not_promote_initial_zero():
    """REQ-TA-FR-002 / QR-004: unavailable calls keep totals nullable."""
    handler = StatsCallbackHandler()
    handler.on_chat_model_start({}, [], run_id="missing")
    handler.on_llm_end(_result([_message()]), run_id="missing")
    stats = handler.get_stats()
    assert stats["llm_calls"] == 1
    assert stats["tokens_in"] is None
    assert stats["tokens_out"] is None
    assert stats["usage_complete"] is False


@pytest.mark.unit
def test_fr002_late_callback_keeps_its_original_run_owner():
    """REQ-TA-FR-002: a delayed prior-run completion never contaminates the active run."""
    first, second = RunBudgetTracker(), RunBudgetTracker()
    handler = UsageCallbackHandler()
    with RunBudgetContext(first).activate():
        handler.on_chat_model_start({}, [], run_id="first-call")
    with RunBudgetContext(second).activate():
        handler.on_chat_model_start({}, [], run_id="second-call")
        handler.on_llm_end(_result([_message({"input_tokens": 12, "output_tokens": 7})]),
                           run_id="first-call")
        assert handler.get_stats()["tokens_in"] is None
        assert handler.get_stats()["llm_calls"] == 1
    assert first.snapshot().total_tokens == 19
    assert second.snapshot().total_tokens is None
    assert handler.tracker is second


@pytest.mark.unit
def test_fr002_late_duplicate_starts_do_not_change_last_run_owner():
    """REQ-TA-FR-002: old tool or model events cannot reselect a prior analysis."""
    first, second = RunBudgetTracker(), RunBudgetTracker()
    handler = UsageCallbackHandler()
    with RunBudgetContext(first).activate():
        handler.on_chat_model_start({}, [], run_id="first-call")
        handler.on_tool_start({}, "", run_id="first-tool")
    with RunBudgetContext(second).activate():
        handler.on_chat_model_start({}, [], run_id="second-call")
    handler.on_chat_model_start({}, [], run_id="first-call")
    handler.on_tool_start({}, "", run_id="first-tool")
    assert handler.tracker is second
    assert first.snapshot().llm_calls == 1
    assert first.snapshot().tool_calls == 1
    assert second.snapshot().tool_calls == 0


@pytest.mark.unit
def test_fr002_callback_error_records_missing_usage_and_accepts_later_measurement():
    """REQ-TA-FR-002: errors do not invent zero and later published usage is idempotent."""
    handler = UsageCallbackHandler()
    handler.on_llm_start({}, [], run_id="failed")
    handler.on_llm_error(RuntimeError("provider failure"), run_id="failed")
    assert handler.get_stats()["usage_complete"] is False
    handler.on_llm_end(_result([_message({"input_tokens": 12, "output_tokens": 7})]),
                       run_id="failed")
    assert handler.get_stats()["llm_calls"] == 1
    assert handler.get_stats()["tokens_in"] == 12


@pytest.mark.unit
def test_fr002_anonymous_legacy_callbacks_pair_in_order():
    """REQ-TA-FR-002: the old no-run-id handler entry points remain usable."""
    handler = StatsCallbackHandler()
    handler.on_chat_model_start({}, [])
    handler.on_llm_end(_result([_message({"input_tokens": 12, "output_tokens": 7})]))
    assert handler.llm_calls == 1
    assert handler.tokens_in == 12
    assert handler.tokens_out == 7
