"""REQ-TA-FR-002: logical invocation and nested callback identities."""

import pytest
from langchain_core.runnables import RunnableLambda

from cli.stats_handler import StatsCallbackHandler
from tradingagents.llm_clients.invocation import (
    BudgetInvocationRefused,
    CallSpec,
    invoke_with_budget,
)
from tradingagents.run_budget import CallRole, RunBudgetContext, RunBudgetTracker

from .test_budget_calls import UsageModel


@pytest.mark.unit
def test_fr002_nested_callbacks_and_constructor_callbacks_charge_one_logical_call():
    tracker = RunBudgetTracker(10)
    stats = StatsCallbackHandler()
    model = UsageModel(callbacks=[stats])
    chain = model | RunnableLambda(lambda message: message)
    with RunBudgetContext(tracker).activate():
        invoke_with_budget(chain, "Offline fixture", call=CallSpec("research", CallRole.OPTIONAL))
    snapshot = tracker.snapshot()
    assert snapshot.llm_calls == 1
    assert snapshot.pending_calls == 0
    assert snapshot.total_tokens == 1


@pytest.mark.unit
def test_fr002_completed_provider_observation_is_not_reinterpreted_without_provider_hint():
    """Native cache semantics already resolved in the callback stay canonical."""
    class AnthropicUsageModel(UsageModel):
        def _get_ls_params(self, **kwargs):
            return {**super()._get_ls_params(**kwargs), "ls_provider": "anthropic"}

    tracker = RunBudgetTracker(100)
    model = AnthropicUsageModel(
        usage={"input_tokens": 35, "output_tokens": 7, "total_tokens": 42},
        raw_usage={"input_tokens": 10, "output_tokens": 7},
    )
    with RunBudgetContext(tracker).activate():
        invoke_with_budget(model, "Offline fixture", call=CallSpec("research", CallRole.OPTIONAL),
                           config={"metadata": {"ls_provider": "anthropic"}})
    assert tracker.snapshot().usage_complete
    assert tracker.snapshot().total_tokens == 42


@pytest.mark.unit
def test_fr002_zero_budget_refuses_before_model_dispatch():
    tracker = RunBudgetTracker(0)
    model = UsageModel()
    with RunBudgetContext(tracker).activate(), pytest.raises(BudgetInvocationRefused) as caught:
        invoke_with_budget(model, "Offline fixture", call=CallSpec("research", CallRole.OPTIONAL))
    assert caught.value.reason_codes == ("ZERO_TOKEN_BUDGET",)
    assert model.calls == []
    assert tracker.snapshot().llm_calls == 0


@pytest.mark.unit
def test_fr002_explicit_invocation_context_cannot_charge_an_enclosing_run():
    """REQ-TA-FR-002/QR-003: explicit call ownership outranks the enclosing context."""
    target, enclosing = RunBudgetTracker(10), RunBudgetTracker(20)
    model = UsageModel()
    chain = model | RunnableLambda(lambda message: {"parsed": "result without usage"})
    with RunBudgetContext(enclosing).activate():
        invoke_with_budget(chain, "Offline fixture", context=RunBudgetContext(target),
                           call=CallSpec("research", CallRole.OPTIONAL))
        assert enclosing.snapshot().llm_calls == 0
    assert target.snapshot().total_tokens == 1
    assert target.snapshot().llm_calls == 1


@pytest.mark.unit
def test_fr002_callback_free_attempt_records_usage_as_unavailable():
    class Adapter:
        def invoke(self, value, config=None):
            return "Parsed adapter result with no usage"

    tracker = RunBudgetTracker(100)
    with RunBudgetContext(tracker).activate():
        invoke_with_budget(Adapter(), "Offline fixture", call=CallSpec("final", CallRole.REQUIRED))
    snapshot = tracker.snapshot()
    assert snapshot.llm_calls == 1 and snapshot.pending_calls == 0
    assert snapshot.known_tokens is None and snapshot.total_tokens is None
    assert snapshot.usage_state == "unavailable"


@pytest.mark.unit
def test_fr002_no_budget_preserves_legacy_invoke_shape():
    class Adapter:
        def invoke(self, value):
            return value

    with RunBudgetContext(RunBudgetTracker()).activate():
        assert invoke_with_budget(Adapter(), "fixture", call=CallSpec("research", CallRole.OPTIONAL)) == "fixture"
