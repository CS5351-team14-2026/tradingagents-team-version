"""REQ-TA-FR-002 call admission through the real offline agent helpers."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from tradingagents.agents.analysts.turn import BUDGET_WRAP_UP, take_turn
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.structured import invoke_structured_or_freetext
from tradingagents.llm_clients.invocation import BudgetInvocationRefused
from tradingagents.run_budget import RunBudgetContext, RunBudgetTracker, UsageObservation


class UsageModel(BaseChatModel):
    """Reports usage from a model nested inside a structured runnable."""

    calls: list = Field(default_factory=list)
    bindings: list = Field(default_factory=list)
    usage: dict | None = Field(default_factory=lambda: {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1})
    raw_usage: dict | None = None
    structured_supported: bool = True
    json_supported: bool = True
    parsed: Any = None

    @property
    def _llm_type(self):
        return "budget-offline"

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(tuple(tools))
        return self

    def with_structured_output(self, schema, **kwargs):
        if not (self.json_supported if kwargs.get("method") == "json_mode" else self.structured_supported):
            raise NotImplementedError
        return self | RunnableLambda(lambda message: self.parsed)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        metadata = {"token_usage": self.raw_usage} if self.raw_usage is not None else {}
        message = AIMessage(content="Report from existing evidence.", usage_metadata=self.usage,
                            response_metadata=metadata)
        return ChatResult(generations=[ChatGeneration(message=message)])


def _exhausted(limit=2):
    tracker = RunBudgetTracker(limit)
    tracker.start_call("earlier")
    tracker.finish_call("earlier", UsageObservation(limit, 0, limit, state="complete"))
    return tracker


def _prompt():
    return ChatPromptTemplate.from_messages([
        ("system", "Use available evidence. Tools: {tool_names}"),
        MessagesPlaceholder("messages"),
    ]).partial(tool_names="offline_tool")


def _pm_state():
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-09",
        "investment_plan": "Existing research plan",
        "trader_investment_plan": "Existing transaction proposal",
        "market_report": "Verified primary evidence",
        "risk_debate_state": {
            "history": "Risk debate evidence",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 0,
        },
    }


@pytest.mark.unit
@pytest.mark.parametrize("usage", [2, 3], ids=["exactly-N", "over-N"])
def test_req_fr002_structured_retry_refusal_never_starts_freetext(usage):
    model = UsageModel(usage={"input_tokens": usage, "output_tokens": 0, "total_tokens": usage})
    tracker = RunBudgetTracker(2)
    with RunBudgetContext(tracker).activate(), pytest.raises(BudgetInvocationRefused):
        invoke_structured_or_freetext(model.with_structured_output(None), model,
                                      "Existing evidence", str, "Trader", phase="trader")

    assert len(model.calls) == 1
    assert tracker.snapshot().known_tokens == usage
    assert tracker.snapshot().blocked_calls == 1


@pytest.mark.unit
@pytest.mark.parametrize("raw_usage,expected", [(None, "unavailable"), ({"prompt_tokens": 1}, "partial")])
def test_req_fr002_incomplete_usage_stops_optional_retry_without_guessing(raw_usage, expected):
    model = UsageModel(usage=None, raw_usage=raw_usage)
    tracker = RunBudgetTracker(100)
    with RunBudgetContext(tracker).activate(), pytest.raises(BudgetInvocationRefused):
        invoke_structured_or_freetext(model.with_structured_output(None), model,
                                      "Existing evidence", str, "Trader")

    assert len(model.calls) == 1
    assert tracker.snapshot().usage_state == expected
    assert tracker.snapshot().total_tokens is None
    assert tracker.snapshot().known_tokens == (1 if raw_usage else None)


@pytest.mark.unit
def test_req_fr002_below_budget_keeps_structured_retries_and_freetext():
    model = UsageModel()
    tracker = RunBudgetTracker(4)
    with RunBudgetContext(tracker).activate():
        result = invoke_structured_or_freetext(model.with_structured_output(None), model,
                                               "Existing evidence", str, "Trader")

    assert result == "Report from existing evidence."
    assert len(model.calls) == 3
    assert tracker.snapshot().total_tokens == 3
    assert tracker.snapshot().blocked_calls == 0


@pytest.mark.unit
def test_req_fr002_unsupported_binding_plain_call_is_required_first_attempt():
    model = UsageModel()
    tracker = _exhausted()
    with RunBudgetContext(tracker).activate():
        result = invoke_structured_or_freetext(None, model, "Existing evidence", str, "Trader")

    assert result == "Report from existing evidence."
    assert len(model.calls) == 1
    assert tracker.snapshot().known_tokens == 3  # A required in-flight call may exceed N.


@pytest.mark.unit
@pytest.mark.parametrize("limit,expected_calls", [(2, 2), (3, 3)], ids=["json-refused", "plain-refused"])
def test_req_fr002_pm_refusal_does_not_escape_into_later_fallback(limit, expected_calls):
    model = UsageModel()
    tracker = RunBudgetTracker(limit)
    with RunBudgetContext(tracker).activate(), pytest.raises(BudgetInvocationRefused):
        create_portfolio_manager(model)(_pm_state())

    assert len(model.calls) == expected_calls
    assert tracker.snapshot().known_tokens == limit


@pytest.mark.unit
@pytest.mark.parametrize("json_supported", [True, False], ids=["json-first", "plain-first"])
def test_req_fr002_pm_first_actual_call_required_when_bindings_unsupported(json_supported):
    model = UsageModel(structured_supported=False, json_supported=json_supported)
    tracker = _exhausted()
    node = create_portfolio_manager(model)
    with RunBudgetContext(tracker).activate():
        if json_supported:
            # The first JSON request runs; its optional plain retry is refused.
            with pytest.raises(BudgetInvocationRefused):
                node(_pm_state())
        else:
            assert node(_pm_state())["final_trade_decision"] == "Report from existing evidence."

    assert len(model.calls) == 1
    assert tracker.snapshot().known_tokens == 3


@pytest.mark.unit
@pytest.mark.parametrize("phase", ["market_analyst", "news_analyst", "fundamentals_analyst"])
def test_req_fr002_each_analyst_tool_followup_is_optional(phase):
    model = UsageModel()
    messages = [HumanMessage(content="Analyze"), ToolMessage(content="Verified tool evidence", tool_call_id="tool-1")]
    tracker = _exhausted()
    with RunBudgetContext(tracker).activate(), pytest.raises(BudgetInvocationRefused):
        take_turn(_prompt(), model, [], messages, phase=phase)

    assert model.calls == []


@pytest.mark.unit
def test_req_fr002_inv003_budget_wrapup_uses_existing_context_without_claiming_tool_limit():
    model = UsageModel()
    messages = [
        HumanMessage(content="Analyze"),
        AIMessage(content="", tool_calls=[{"name": "offline_tool", "args": {}, "id": "tool-1"}]),
        ToolMessage(content="Verified tool evidence", tool_call_id="tool-1"),
        HumanMessage(content=BUDGET_WRAP_UP),
    ]
    tracker = _exhausted()
    with RunBudgetContext(tracker).activate():
        _, report = take_turn(_prompt(), model, [], messages, phase="market_analyst")

    assert report
    assert len(model.calls) == 1
    assert model.bindings == []
    assert not any(isinstance(message, ToolMessage) or getattr(message, "tool_calls", None)
                   for message in model.calls[0])
    text = "\n".join(str(message.content) for message in model.calls[0])
    assert "Verified tool evidence" in text and "token budget" in text
    assert "tool rounds are spent" not in text and "every tool round" not in text


@pytest.mark.unit
def test_req_fr002_research_manager_receives_skipped_debate_and_primary_evidence():
    model = UsageModel(structured_supported=False)
    tracker = _exhausted()
    state = {
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-09",
        "market_report": "Verified analyst evidence",
        "investment_debate_state": {"history": "", "count": 0, "budget_skipped": True},
    }
    with RunBudgetContext(tracker).activate():
        assert create_research_manager(model)(state)["investment_plan"]

    text = "\n".join(str(message.content) for message in model.calls[0])
    assert "optional research contributions were skipped" in text
    assert "Verified analyst evidence" in text


@pytest.mark.unit
def test_req_fr002_no_budget_preserves_all_existing_fallback_calls():
    model = UsageModel(usage=None)
    with RunBudgetContext(RunBudgetTracker()).activate():
        result = invoke_structured_or_freetext(model.with_structured_output(None), model,
                                               "Existing evidence", str, "Trader")

    assert result == "Report from existing evidence."
    assert len(model.calls) == 3
