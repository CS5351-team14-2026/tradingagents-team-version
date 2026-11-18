import logging
from collections import Counter
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_fundamentals_analyst,
    create_market_analyst,
    create_neutral_debator,
    create_news_analyst,
    create_portfolio_manager,
    create_research_manager,
    create_sentiment_analyst,
    create_trader,
)
from tradingagents.agents.analysts.turn import WRAP_UP
from tradingagents.agents.state import AgentState
from tradingagents.llm_clients.invocation import admit_optional

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic

logger = logging.getLogger(__name__)

# Every target a shared conditional router can return. Each edge driven by the
# router maps all of them, so a fall-through return (e.g. under prompt/i18n/
# refactor drift in the speaker labels) can never hit a missing path_map entry
# and crash LangGraph mid-run (#1088).
DEBATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}
RISK_ANALYSIS_PATH_MAP = {
    "Aggressive Analyst": "Aggressive Analyst",
    "Conservative Analyst": "Conservative Analyst",
    "Neutral Analyst": "Neutral Analyst",
    "Portfolio Manager": "Portfolio Manager",
}

# The skip marker a budget-refused optional node leaves in its debate/risk state
# so the router ends the phase instead of scheduling another optional turn
# (Implements: ADR-004; REQ-TA-FR-002).
_BUDGET_SKIP_NOTE = "budget_exhausted"


def _budget_optional_node(node, *, state_key: str, outcome_key: str, phase: str, terminal_count: int):
    """Wrap an optional debate/risk node with an admission gate (ADR-004).

    Before the node makes its LLM call, this asks the run's budget whether an
    OPTIONAL call may start. When refused, it returns a controlled skip marker
    (no LLM call) that the conditional router recognises to end the phase. A
    required synthesis node is not wrapped: it always runs.

    ``terminal_count`` is the ``count`` the phase's router treats as finished
    (``2 * max_debate_rounds`` or ``3 * max_risk_discuss_rounds``). The wrapper
    forces it on refusal so no further optional turn is requested.

    The wrapper preserves the node's normal return when admitted; it never
    cancels an already-started call (D5).
    """

    def wrapped(state):
        admission = admit_optional(phase)
        if admission.allowed:
            return node(state)
        # Refused: append a marked turn so the router sees the phase cannot
        # continue. No request is issued and no verdict is fabricated.
        previous = state.get(state_key) or {}
        note = (
            f"[Budget control: optional {phase} contribution was skipped "
            f"({', '.join(admission.reason_codes)}); this phase did not complete.]"
        )
        new_state = dict(previous)
        new_state[outcome_key] = (previous.get(outcome_key, "") + "\n" + note).strip()
        new_state["history"] = (previous.get("history", "") + "\n" + note).strip()
        if "current_response" in previous:
            new_state["current_response"] = note
        new_state["count"] = terminal_count
        new_state[_BUDGET_SKIP_NOTE] = True
        new_state["budget_reason_codes"] = list(admission.reason_codes)
        return {state_key: new_state}

    return wrapped


def _tools_or_done(state) -> str:
    """Route an analyst's turn: run its tool calls, or finish with its report."""
    return "tools" if state["messages"][-1].tool_calls else END


def _analyst_graph(spec, agent, max_tool_rounds: int):
    """One analyst as a graph of its own: the model and its tools, on a private message history.

    It returns only its report, so analysts running side by side never write the
    same key, and its tool calls never reach the other analysts' messages. After
    ``max_tool_rounds`` rounds of tool calls it is told to write its report, and
    that turn ends it whatever it answers, so a model that keeps calling tools
    cannot run the graph into its recursion limit (#1420).
    """
    output = TypedDict(f"{spec.key.capitalize()}Report", {spec.report_key: str})
    graph = StateGraph(AgentState, output_schema=output)
    graph.add_node("agent", agent)
    graph.add_edge(START, "agent")
    if not spec.tools:
        graph.add_edge("agent", END)
        return graph.compile()

    def calls(messages):
        return [call["name"] for m in messages for call in (getattr(m, "tool_calls", None) or [])]

    def rounds(messages) -> int:
        return sum(1 for m in messages if getattr(m, "tool_calls", None))

    def more_or_wrap_up(state) -> str:
        # The analyst's follow-up turns after a tool round are OPTIONAL: stop
        # them (to the required wrap-up) once the budget refuses, never bypassing
        # the tool-round cap (Implements: ADR-004; REQ-TA-FR-002; REQ-TA-INV-003).
        if rounds(state["messages"]) >= max_tool_rounds:
            return "wrap_up"
        if not admit_optional("analyst_followup").allowed:
            return "wrap_up"
        return "agent"

    def wrap_up(state):
        repeated = ", ".join(f"{name} x{n}" for name, n in Counter(calls(state["messages"])).most_common())
        logger.warning("%s used its %d tool rounds (%s); asking for its report",
                       spec.agent_node, max_tool_rounds, repeated)
        return agent({**state, "messages": [*state["messages"], HumanMessage(WRAP_UP)]})

    graph.add_node("tools", ToolNode(list(spec.tools)))
    graph.add_node("wrap_up", wrap_up)
    graph.add_conditional_edges("agent", _tools_or_done, ["tools", END])
    graph.add_conditional_edges("tools", more_or_wrap_up, ["agent", "wrap_up"])
    graph.add_edge("wrap_up", END)
    return graph.compile()


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        conditional_logic: ConditionalLogic,
        max_tool_rounds: int,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.conditional_logic = conditional_logic
        self.max_tool_rounds = max_tool_rounds

    def setup_graph(
        self, selected_analysts=("market", "social", "news", "fundamentals"), memory_node=None
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Sentiment analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
            memory_node: Node that settles past decisions and returns the run's
                ``past_context``. It runs alongside the analysts.
        """
        plan = build_analyst_execution_plan(selected_analysts)

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(self.quick_thinking_llm),
            "fundamentals": lambda: create_fundamentals_analyst(self.quick_thinking_llm),
        }

        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # The count each phase's router treats as finished, so a budget-refused
        # optional turn can end its phase cleanly (ADR-004; REQ-TA-FR-002).
        terminal_debate = 2 * self.conditional_logic.max_debate_rounds
        terminal_risk = 3 * self.conditional_logic.max_risk_discuss_rounds

        workflow = StateGraph(AgentState)

        for spec in plan.specs:
            workflow.add_node(spec.agent_node,
                              _analyst_graph(spec, analyst_factories[spec.key](), self.max_tool_rounds))

        workflow.add_node("Bull Researcher",
                          _budget_optional_node(bull_researcher_node,
                                                state_key="investment_debate_state",
                                                outcome_key="bull_history",
                                                phase="debate",
                                                terminal_count=terminal_debate))
        workflow.add_node("Bear Researcher",
                          _budget_optional_node(bear_researcher_node,
                                                state_key="investment_debate_state",
                                                outcome_key="bear_history",
                                                phase="debate",
                                                terminal_count=terminal_debate))
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst",
                          _budget_optional_node(aggressive_analyst,
                                                state_key="risk_debate_state",
                                                outcome_key="aggressive_history",
                                                phase="risk",
                                                terminal_count=terminal_risk))
        workflow.add_node("Neutral Analyst",
                          _budget_optional_node(neutral_analyst,
                                                state_key="risk_debate_state",
                                                outcome_key="neutral_history",
                                                phase="risk",
                                                terminal_count=terminal_risk))
        workflow.add_node("Conservative Analyst",
                          _budget_optional_node(conservative_analyst,
                                                state_key="risk_debate_state",
                                                outcome_key="conservative_history",
                                                phase="risk",
                                                terminal_count=terminal_risk))
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # The analysts work at the same time; the research debate starts once
        # every one of them has filed its report. The memory log settles past
        # decisions alongside them: only the Portfolio Manager reads its lessons.
        first_steps = [spec.agent_node for spec in plan.specs]
        if memory_node is not None:
            workflow.add_node("Memory Log", memory_node)
            first_steps.append("Memory Log")
        for node in first_steps:
            workflow.add_edge(START, node)
        workflow.add_edge(first_steps, "Bull Researcher")

        # Both research-debate edges share the complete DEBATE_PATH_MAP (#1088).
        for debate_node in ("Bull Researcher", "Bear Researcher"):
            workflow.add_conditional_edges(
                debate_node,
                self.conditional_logic.should_continue_debate,
                DEBATE_PATH_MAP,
            )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        # All three risk edges share the complete RISK_ANALYSIS_PATH_MAP (#1088).
        for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
            workflow.add_conditional_edges(
                risk_node,
                self.conditional_logic.should_continue_risk_analysis,
                RISK_ANALYSIS_PATH_MAP,
            )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
