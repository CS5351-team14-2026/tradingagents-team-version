"""Per-invocation graph budget gates (REQ-TA-FR-002; ADR-003; INV-003)."""

from __future__ import annotations

import copy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_neutral_debator,
)
from tradingagents.agents.analysts.turn import BUDGET_WRAP_UP
from tradingagents.graph.analyst_execution import AnalystNodeSpec
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import (
    DEBATE_PATH_MAP,
    RISK_ANALYSIS_PATH_MAP,
    _analyst_graph,
    _budget_optional_node,
)
from tradingagents.llm_clients.invocation import BudgetInvocationRefused, CallSpec
from tradingagents.run_budget import CallRole, RunBudgetContext, RunBudgetTracker, UsageObservation

from . import test_budget_entrypoints as budget_doubles, test_graph_end_to_end as graph_doubles

offline = graph_doubles.offline


def _state():
    state = Propagator().create_initial_state("NVDA", graph_doubles.TRADE_DATE)
    state.update(dict.fromkeys(("market_report", "sentiment_report", "news_report", "fundamentals_report"), "Available analyst evidence"))
    state["trader_investment_plan"] = "Available trading proposal"
    return state


class RecordingModel:
    def __init__(self):
        self.calls = []

    def invoke(self, prompt, config=None):
        self.calls.append(prompt)
        return AIMessage(content="An evidence-based contribution", usage_metadata={
            "input_tokens": 3, "output_tokens": 2, "total_tokens": 5})


OPTIONAL_NODES = [
    (create_bull_researcher, "investment_debate_state", "research.bull"),
    (create_bear_researcher, "investment_debate_state", "research.bear"),
    (create_aggressive_debator, "risk_debate_state", "risk.aggressive"),
    (create_conservative_debator, "risk_debate_state", "risk.conservative"),
    (create_neutral_debator, "risk_debate_state", "risk.neutral"),
]


@pytest.mark.unit
@pytest.mark.parametrize("factory,state_key,phase", OPTIONAL_NODES, ids=[n[2] for n in OPTIONAL_NODES])
@pytest.mark.parametrize("limit", [4, 5], ids=["above-limit", "at-limit"])
@pytest.mark.parametrize("count", [0, 1], ids=["phase-entry", "continuation"])
def test_fr002_every_research_and_risk_call_is_blocked_after_recorded_limit(
        factory, state_key, phase, limit, count):
    """REQ-TA-FR-002: first and later optional calls never dispatch at/above N."""
    tracker = RunBudgetTracker(limit)
    tracker.start_call("reported")
    tracker.finish_call("reported", UsageObservation(3, 2, 5, "complete"))
    model = RecordingModel()
    state = _state()
    state[state_key]["count"] = count
    state[state_key]["history"] = "Earlier work remains available"
    before = copy.deepcopy(state[state_key])

    with RunBudgetContext(tracker).activate():
        result = _budget_optional_node(factory(model), state_key)(state)[state_key]

    assert model.calls == []
    assert state[state_key] == before
    assert result["count"] == count
    assert result["budget_skipped"] is True
    assert result["budget_reason_codes"]
    assert phase in result["history"] and "did not complete normally" in result["history"]
    assert before["history"] in result["history"]
    state[state_key] = result
    logic = ConditionalLogic()
    if state_key == "investment_debate_state":
        assert logic.should_continue_debate(state) == "Research Manager"
    else:
        assert logic.should_continue_risk_analysis(state) == "Portfolio Manager"


@pytest.mark.unit
@pytest.mark.parametrize("factory,state_key,phase", OPTIONAL_NODES, ids=[n[2] for n in OPTIONAL_NODES])
def test_fr002_an_admitted_contribution_can_exceed_n_and_blocks_its_successor(factory, state_key, phase):
    """REQ-TA-FR-002: admission permits an in-flight overshoot, never a hard cap."""
    tracker = RunBudgetTracker(4)
    model = RecordingModel()
    node = _budget_optional_node(factory(model), state_key)
    state = _state()
    with RunBudgetContext(tracker).activate():
        state.update(node(state))
        assert tracker.snapshot().known_tokens == 5 > tracker.limit
        state.update(node(state))

    assert len(model.calls) == 1, phase
    assert state[state_key]["count"] == 1
    assert state[state_key]["budget_skipped"] is True


@pytest.mark.unit
@pytest.mark.parametrize("factory,state_key,phase", OPTIONAL_NODES, ids=[n[2] for n in OPTIONAL_NODES])
@pytest.mark.parametrize("observation", [UsageObservation(3, None, None, "partial"), UsageObservation()],
                         ids=["partial", "unavailable"])
def test_fr002_incomplete_usage_blocks_real_optional_dispatch_without_fabricated_zero(
        factory, state_key, phase, observation):
    """REQ-TA-FR-002 D1–D3: unknown totals conservatively stop optional work."""
    tracker = RunBudgetTracker(100)
    tracker.start_call("incomplete")
    tracker.finish_call("incomplete", observation)
    model = RecordingModel()
    with RunBudgetContext(tracker).activate():
        result = _budget_optional_node(factory(model), state_key)(_state())

    assert model.calls == [], phase
    assert result[state_key]["budget_skipped"] is True
    assert tracker.snapshot().status == "BUDGET_WARNING"
    assert tracker.snapshot().total_tokens is None
    assert tracker.snapshot().tokens_out is None


@pytest.mark.unit
def test_fr002_preserves_complete_router_path_maps():
    """REQ-TA-FR-002/INV-003: refusal adds no unmapped route or replacement loop."""
    assert {name: name for name in (
        "Bull Researcher", "Bear Researcher", "Research Manager")} == DEBATE_PATH_MAP
    assert {name: name for name in (
        "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager")} == RISK_ANALYSIS_PATH_MAP


def _refusal():
    return BudgetInvocationRefused(
        CallSpec(phase="market_analyst", role=CallRole.OPTIONAL), ("RECORDED_USAGE_REACHED_LIMIT",))


@pytest.mark.unit
def test_fr002_analyst_with_context_gets_one_required_budget_wrapup():
    """REQ-TA-FR-002/INV-003: refused follow-up cannot start another tool round."""
    seen = []

    def agent(state):
        seen.append(state["messages"])
        if isinstance(state["messages"][-1], HumanMessage) and state["messages"][-1].content == BUDGET_WRAP_UP:
            return {"messages": [AIMessage(content="Report from existing results")],
                    "market_report": "Report from existing results"}
        raise _refusal()

    # The run resumes after a completed tool step; the fake tool is never bound
    # or called because the refused optional LLM turn goes straight to synthesis.
    @tool
    def available_tool() -> str:
        """Supply data only when a new tool round is actually requested."""
        pytest.fail("A refused analyst follow-up started a tool")

    spec = AnalystNodeSpec("market", "Market Analyst", "market_report", (available_tool,))
    state = _state()
    state["messages"] = [HumanMessage("NVDA"), AIMessage(content="", tool_calls=[{
        "id": "old", "name": "available_tool", "args": {}}]),
        ToolMessage(content="Measured prices", tool_call_id="old")]
    result = _analyst_graph(spec, agent, max_tool_rounds=3).invoke(state)

    assert len(seen) == 2
    assert seen[-1][-1].content == BUDGET_WRAP_UP
    assert "existing results" in result["market_report"]
    assert "optional analyst follow-up was skipped" in result["market_report"]


@pytest.mark.unit
def test_fr002_unstarted_analyst_cannot_invent_a_required_wrapup():
    """REQ-TA-FR-002: no tool context must propagate to controlled run failure."""
    seen = []

    def agent(state):
        seen.append(state)
        raise _refusal()

    spec = AnalystNodeSpec("social", "Sentiment Analyst", "sentiment_report")
    with pytest.raises(BudgetInvocationRefused):
        _analyst_graph(spec, agent, max_tool_rounds=3).invoke(_state())
    assert len(seen) == 1


class PromptUsageModel(budget_doubles.UsageModel):
    prompts: list = Field(default_factory=list)

    def _generate(self, messages, *args, **kwargs):
        self.prompts.append("\n".join(str(message.content) for message in messages))
        return super()._generate(messages, *args, **kwargs)


@pytest.mark.unit
def test_fr002_zero_budget_skips_initial_debate_and_risk_but_keeps_required_synthesis(
        tmp_path, monkeypatch, offline):
    """REQ-TA-FR-002/QR-003/INV-003: direct graph gates entry and reports omissions."""
    model = PromptUsageModel()
    graph = budget_doubles._graph(tmp_path, monkeypatch, model)
    tracker = RunBudgetTracker(0)
    with RunBudgetContext(tracker).activate():
        state, signal = graph.propagate("NVDA", graph_doubles.TRADE_DATE)

    assert signal == "Overweight"
    assert state["investment_debate_state"]["count"] == state["risk_debate_state"]["count"] == 0
    assert state["investment_debate_state"]["budget_skipped"] is True
    assert state["risk_debate_state"]["budget_skipped"] is True
    assert all(state[key].strip() for key in (
        "market_report", "news_report", "fundamentals_report", "investment_plan", "final_trade_decision"))
    assert not any("You are a Bull Analyst" in prompt or "As the Aggressive Risk Analyst" in prompt
                   for prompt in model.prompts)
    assert sum(BUDGET_WRAP_UP in prompt for prompt in model.prompts) == 3
    assert any("did not complete normally" in prompt for prompt in model.prompts)
    assert tracker.snapshot().llm_calls == len(model.calls)
    assert tracker.snapshot().status == "BUDGET_EXHAUSTED"
    assert tracker.snapshot().known_tokens == 5 * len(model.calls) > 0
